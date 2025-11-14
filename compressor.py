import time
import os

# Simple pure-Python LZ compressor/decompressor used for indices (v6)
def _lz_compress(data: bytes) -> bytes:
    # faster hash-based sliding-window LZ: tokens are (flag, ...)
    # flag 0x00: literal -> next byte is literal
    # flag 0x01: match   -> next 2 bytes = offset (big-endian), next 1 byte = length
    if not data:
        return b""

    from collections import defaultdict, deque

    window_size = 4095  # fits in 2 bytes
    min_match = 4
    max_match = 255
    max_positions_per_key = 32

    out = bytearray()
    n = len(data)
    pos = 0

    # index recent positions by a short prefix (min_match bytes)
    table = defaultdict(deque)

    while pos < n:
        best_len = 0
        best_off = 0

        if pos + min_match <= n:
            key = data[pos:pos+min_match]
            candidates = table.get(key, None)
            if candidates:
                # search candidates from newest to oldest
                for candidate in reversed(candidates):
                    off = pos - candidate
                    if off > window_size:
                        # candidate too far back
                        continue
                    # extend match
                    length = 0
                    # ensure candidate+length < pos to avoid overlap issues
                    while (length < max_match and pos + length < n and
                           data[candidate + length] == data[pos + length]):
                        length += 1
                    if length > best_len:
                        best_len = length
                        best_off = off
                        if best_len >= max_match:
                            break

        if best_len >= min_match:
            out.append(1)
            out.extend(best_off.to_bytes(2, 'big'))
            out.append(best_len)
            # add intermediate positions into table for future matches
            endp = pos + best_len
            for p in range(pos, endp):
                if p + min_match <= n:
                    k = data[p:p+min_match]
                    dq = table[k]
                    dq.append(p)
                    if len(dq) > max_positions_per_key:
                        dq.popleft()
            pos += best_len
        else:
            out.append(0)
            out.append(data[pos])
            if pos + min_match <= n:
                k = data[pos:pos+min_match]
                dq = table[k]
                dq.append(pos)
                if len(dq) > max_positions_per_key:
                    dq.popleft()
            pos += 1

    return bytes(out)


def _lz_decompress(comp: bytes) -> bytes:
    if not comp:
        return b""
    out = bytearray()
    pos = 0
    n = len(comp)
    while pos < n:
        flag = comp[pos]; pos += 1
        if flag == 0:
            if pos >= n:
                raise ValueError("Corrupt LZ stream: literal missing byte")
            out.append(comp[pos]); pos += 1
        elif flag == 1:
            if pos + 3 > n:
                raise ValueError("Corrupt LZ stream: match header truncated")
            offset = int.from_bytes(comp[pos:pos+2], 'big'); pos += 2
            length = comp[pos]; pos += 1
            if offset <= 0 or offset > len(out):
                raise ValueError("Corrupt LZ stream: invalid offset")
            start = len(out) - offset
            for i in range(length):
                out.append(out[start + i])
        else:
            raise ValueError("Corrupt LZ stream: unknown flag")

    return bytes(out)


class BMPCompressor:

    def __init__(self):
        # allow larger palettes by increasing dictionary size (raise upper limit)
        # previous default (65536) was too small for images with many unique colors
        self.max_dict_size = 1 << 18  # 262144 entries

    def compress(self, pixel_data, output_file, input_path):
        # flatten pixels as symbols, tuples
        symbols = []
        for row in pixel_data:
            for pix in row:
                symbols.append(tuple(pix))

        # build palette of unique pixels in appearance order
        palette = []
        index_map = {}
        for pix in symbols:
            if pix not in index_map:
                index_map[pix] = len(palette)
                palette.append(pix)

        # map symbol stream to indices
        indices = [index_map[p] for p in symbols]

        original_size = os.path.getsize(input_path)
        height = len(pixel_data)
        width = len(pixel_data[0]) if height > 0 else 0

        start_time = time.time()

        # pack indices into minimal byte-width (raw bytes option)
        palette_count = len(palette)
        if palette_count <= 1:
            bytes_per_index = 1
        else:
            bits_needed = (palette_count - 1).bit_length()
            bytes_per_index = max(1, (bits_needed + 7) // 8)

        indices_bytes = bytearray()
        for idx in indices:
            indices_bytes.extend(idx.to_bytes(bytes_per_index, 'big'))

        # raw indices payload (byte-aligned) and original BMP bytes
        raw_indices_payload = bytes(indices_bytes)

        # New: bit-packed indices payload (v5) -- pack indices tightly using bits_needed
        if palette_count <= 1:
            bits_per_index = 1
        else:
            bits_per_index = (palette_count - 1).bit_length()

        # MSB-first packing: accumulate bits in buffer and flush top bytes
        packed_bits_out = bytearray()
        bit_buf = 0
        bit_count = 0
        for idx in indices:
            # append code bits
            bit_buf = (bit_buf << bits_per_index) | (idx & ((1 << bits_per_index) - 1))
            bit_count += bits_per_index
            while bit_count >= 8:
                shift = bit_count - 8
                byte = (bit_buf >> shift) & 0xFF
                packed_bits_out.append(byte)
                bit_count -= 8
                bit_buf &= (1 << bit_count) - 1 if bit_count > 0 else 0

        if bit_count > 0:
            # pad the last partial byte with zeros on the right (LSB)
            byte = (bit_buf << (8 - bit_count)) & 0xFF
            packed_bits_out.append(byte)

        packed_bits_payload = bytes(packed_bits_out)
        original_bytes = open(input_path, 'rb').read()

        # compute estimated sizes for each strategy (full file size)
        base_header = 7 + 1 + 4 + 4 + 4 + 4 + (len(palette) * 3)
        size_v3 = base_header + 1 + 4 + len(raw_indices_payload)  # bytes_per_index(1) + payload_len(4) + payload
        size_v5 = base_header + 1 + 4 + len(packed_bits_payload)  # bits_per_index(1) + payload_len(4) + payload
        size_v4 = 7 + 1 + 4 + 4 + 4 + 4  + 4 + len(original_bytes)  # magic + version + header + palette_len(0) + payload_len + raw bmp

        # pick best among v3 (byte-aligned), v5 (bit-packed) and v4 (embed original)
        # prefer the most-compact container that is smaller than original; otherwise embed original
        # also consider LZ-compressed raw indices (v6)
        compressed_v6 = _lz_compress(raw_indices_payload)
        size_v6 = base_header + 1 + 4 + len(compressed_v6)  # bytes_per_index(1) + payload_len(4) + payload

        candidates = [(3, size_v3), (5, size_v5), (6, size_v6), (4, size_v4)]
        # choose smallest size among candidates
        chosen_version, chosen_size = min(candidates, key=lambda x: x[1])
        if chosen_size >= original_size:
            chosen_version = 4

        # write single, consistent header and payload according to chosen_version
        with open(output_file, 'wb') as f:
            f.write(b"CMPT365")
            f.write(bytes([chosen_version]))
            f.write(original_size.to_bytes(4, 'big'))
            f.write(width.to_bytes(4, 'big'))
            f.write(height.to_bytes(4, 'big'))

            if chosen_version == 4:
                # indicate no palette when embedding raw BMP
                f.write((0).to_bytes(4, 'big'))
            else:
                f.write(len(palette).to_bytes(4, 'big'))
                for (r, g, b) in palette:
                    f.write(bytes([r, g, b]))

            if chosen_version == 3:
                f.write(bytes([bytes_per_index]))
                f.write(len(raw_indices_payload).to_bytes(4, 'big'))
                f.write(raw_indices_payload)
            elif chosen_version == 5:
                # write bits_per_index (1 byte), payload length (4 bytes), then bit-packed payload
                f.write(bytes([bits_per_index]))
                f.write(len(packed_bits_payload).to_bytes(4, 'big'))
                f.write(packed_bits_payload)
            elif chosen_version == 6:
                # write bytes_per_index (1 byte), payload length (4 bytes), then LZ-compressed raw indices
                f.write(bytes([bytes_per_index]))
                f.write(len(compressed_v6).to_bytes(4, 'big'))
                f.write(compressed_v6)
            else:  # version 4: embed original BMP
                f.write(len(original_bytes).to_bytes(4, 'big'))
                f.write(original_bytes)

        end_time = time.time()

        compressed_size = os.path.getsize(output_file)
        ratio = original_size / compressed_size if compressed_size > 0 else 0
        time_ms = (end_time - start_time) * 1000

        return {
            "original_size": original_size,
            "compressed_size": compressed_size,
            "ratio": ratio,
            "time_ms": time_ms,
            "palette_len": len(palette)
        }

    def _lzw_pack_indices_to_bits(self, data):
        # Implements LZW and packs codes to a bitstream with dynamic code width.
        # Writes bits LSB-first into the output bytes.
        if not data:
            return b""

        # initial dictionary contains all single-symbols seen in palette
        init_dict_size = max(data) + 1
        dictionary = { (i,): i for i in range(init_dict_size) }
        dict_size = init_dict_size
        code_width = max(1, (dict_size - 1).bit_length())

        out = bytearray()
        bit_buf = 0
        bit_count = 0

        def write_code(code, width):
            nonlocal bit_buf, bit_count
            bit_buf |= (code << bit_count)
            bit_count += width
            while bit_count >= 8:
                out.append(bit_buf & 0xFF)
                bit_buf >>= 8
                bit_count -= 8

        s = (data[0],)
        for c in data[1:]:
            sc = s + (c,)
            if sc in dictionary:
                s = sc
            else:
                write_code(dictionary[s], code_width)
                if dict_size < self.max_dict_size:
                    dictionary[sc] = dict_size
                    dict_size += 1
                    # increase code width when we've filled current width
                    if dict_size == (1 << code_width):
                        code_width += 1
                s = (c,)

        if s:
            write_code(dictionary[s], code_width)

        if bit_count > 0:
            out.append(bit_buf & 0xFF)

        return bytes(out)


class BMPDecompressor:
    def decompress(self, input_file):

        with open(input_file, 'rb') as f:
            data = f.read()

        if not data.startswith(b"CMPT365"):
            raise ValueError("Not a CMPT365 file")

        pos = 7
        # read version byte
        version = data[pos]; pos += 1
        if version not in (2, 3, 4, 5, 6):
            raise ValueError("Unsupported CMPT365 version")

        original_size = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
        width = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
        height = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
        palette_len = int.from_bytes(data[pos:pos+4], 'big'); pos += 4

        palette = []
        for _ in range(palette_len):
            r = data[pos]; g = data[pos+1]; b = data[pos+2]
            palette.append((r, g, b))
            pos += 3

        # For version 3 we parse the payload inside the v3 branch (to support
        # the optional bytes-per-index header). For version 5 we parse the
        # bit-packed payload (bits_per_index). For version 2 below we'll read
        # the payload length and payload then.

        # support version 3 (raw indices packed with bytes_per_index)
        if version == 3:
            # read bytes_per_index + payload
            if pos >= len(data):
                raise ValueError("Corrupt file: missing bytes_per_index/payload length")
            bytes_per_index = data[pos]; pos += 1
            if pos + 4 > len(data):
                raise ValueError("Corrupt file: missing payload length")
            payload_len = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
            if pos + payload_len > len(data):
                raise ValueError("Corrupt file: truncated payload")
            packed = data[pos:pos+payload_len]
            # parse indices from packed raw bytes
            if len(packed) % bytes_per_index != 0:
                raise ValueError("Corrupt payload: indices length not multiple of bytes_per_index")
            result_indices = []
            for i in range(0, len(packed), bytes_per_index):
                result_indices.append(int.from_bytes(packed[i:i+bytes_per_index], 'big'))

            # map indices back to pixels and reshape into rows
            pixels = [ palette[i] if 0 <= i < len(palette) else (0,0,0) for i in result_indices ]

            rows = []
            idx = 0
            for _ in range(height):
                row = []
                for _ in range(width):
                    if idx < len(pixels):
                        row.append(pixels[idx])
                    else:
                        row.append((0,0,0))
                    idx += 1
                rows.append(row)

            return (rows, width, height, original_size)

        # support version 5: bit-packed indices payload
        if version == 5:
            if pos >= len(data):
                raise ValueError("Corrupt file: missing bits_per_index/payload length")
            bits_per_index = data[pos]; pos += 1
            if pos + 4 > len(data):
                raise ValueError("Corrupt file: missing payload length")
            payload_len = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
            if pos + payload_len > len(data):
                raise ValueError("Corrupt file: truncated payload")
            packed = data[pos:pos+payload_len]

            # unpack MSB-first stream into indices
            expected_count = width * height
            result_indices = []
            bit_buf = 0
            bit_count = 0
            mask = (1 << bits_per_index) - 1
            for b in packed:
                bit_buf = (bit_buf << 8) | b
                bit_count += 8
                while bit_count >= bits_per_index and len(result_indices) < expected_count:
                    shift = bit_count - bits_per_index
                    code = (bit_buf >> shift) & mask
                    result_indices.append(code)
                    bit_count -= bits_per_index
                    bit_buf &= (1 << bit_count) - 1 if bit_count > 0 else 0

            if len(result_indices) < expected_count:
                raise ValueError("Corrupt payload: not enough indices in bit-packed payload")

            pixels = [ palette[i] if 0 <= i < len(palette) else (0,0,0) for i in result_indices[:expected_count] ]

            rows = []
            idx = 0
            for _ in range(height):
                row = []
                for _ in range(width):
                    if idx < len(pixels):
                        row.append(pixels[idx])
                    else:
                        row.append((0,0,0))
                    idx += 1
                rows.append(row)

            return (rows, width, height, original_size)

        # support version 6: LZ-compressed raw indices (byte-aligned)
        if version == 6:
            if pos >= len(data):
                raise ValueError("Corrupt file: missing bytes_per_index/payload length")
            bytes_per_index = data[pos]; pos += 1
            if pos + 4 > len(data):
                raise ValueError("Corrupt file: missing payload length")
            payload_len = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
            if pos + payload_len > len(data):
                raise ValueError("Corrupt file: truncated payload")
            packed = data[pos:pos+payload_len]
            # decompress LZ to get raw indices bytes
            raw = _lz_decompress(packed)
            if len(raw) % bytes_per_index != 0:
                raise ValueError("Corrupt payload: indices length not multiple of bytes_per_index")
            result_indices = []
            for i in range(0, len(raw), bytes_per_index):
                result_indices.append(int.from_bytes(raw[i:i+bytes_per_index], 'big'))

            pixels = [ palette[i] if 0 <= i < len(palette) else (0,0,0) for i in result_indices ]

            rows = []
            idx = 0
            for _ in range(height):
                row = []
                for _ in range(width):
                    if idx < len(pixels):
                        row.append(pixels[idx])
                    else:
                        row.append((0,0,0))
                    idx += 1
                rows.append(row)

            return (rows, width, height, original_size)

        # support version 4: raw BMP stored inside container
        if version == 4:
            if pos + 4 > len(data):
                raise ValueError("Corrupt file: missing payload length")
            payload_len = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
            if pos + payload_len > len(data):
                raise ValueError("Corrupt file: truncated payload")
            raw_bmp = data[pos:pos+payload_len]
            # parse BMP bytes using BMPParser by writing a temp file
            import tempfile
            from bmp_parser import BMPParser
            tf = tempfile.NamedTemporaryFile(delete=False, suffix='.bmp')
            try:
                tf.write(raw_bmp)
                tf.flush()
                tf.close()
                parser = BMPParser(tf.name)
                parser.load()
                rows = parser.pixel_data
                width = parser.metadata['width']
                height = abs(parser.metadata['height'])
                return (rows, width, height, original_size)
            finally:
                try:
                    import os
                    os.unlink(tf.name)
                except Exception:
                    pass

        # fall back to version 2 LZW decoder for backwards compatibility

        # read payload length and payload for v2
        if version == 2:
            if pos + 4 > len(data):
                raise ValueError("Corrupt file: missing payload length")
            payload_len = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
            if pos + payload_len > len(data):
                raise ValueError("Corrupt file: truncated payload")
            packed = data[pos:pos+payload_len]

        # Streaming bit-level LZW decode (LSB-first) for version 2
        bit_buf = 0
        bit_count = 0
        byte_pos = 0

        def read_bits(n):
            nonlocal bit_buf, bit_count, byte_pos
            while bit_count < n:
                if byte_pos < len(packed):
                    bit_buf |= packed[byte_pos] << bit_count
                    byte_pos += 1
                    bit_count += 8
                else:
                    return None
            mask = (1 << n) - 1
            val = bit_buf & mask
            bit_buf >>= n
            bit_count -= n
            return val

        dict_size = palette_len if palette_len > 0 else 0
        dictionary = { i: (i,) for i in range(dict_size) }
        max_dict_size = self.max_dict_size if hasattr(self, 'max_dict_size') else (1 << 18)

        code_width = max(1, (dict_size - 1).bit_length())

        first = read_bits(code_width)
        if first is None:
            rows = [ [ (0,0,0) for _ in range(width) ] for _ in range(height) ]
            return (rows, width, height, original_size)

        if first not in dictionary:
            raise ValueError("Corrupt compressed data: first code invalid")

        result_indices = []
        result_indices.extend(dictionary[first])
        prev_code = first

        while True:
            if dict_size == (1 << code_width):
                code_width += 1

            code = read_bits(code_width)
            if code is None:
                break

            if code in dictionary:
                entry = dictionary[code]
            elif code == dict_size:
                entry = dictionary[prev_code] + (dictionary[prev_code][0],)
            else:
                raise ValueError(
                    f"Bad compressed code: code={code} prev_code={prev_code} dict_size={dict_size} "
                    f"code_width={code_width} byte_pos={byte_pos} bit_count={bit_count} packed_len={len(packed)}"
                )

            result_indices.extend(entry)

            if dict_size < max_dict_size:
                dictionary[dict_size] = dictionary[prev_code] + (entry[0],)
                dict_size += 1

            prev_code = code

        # map indices back to pixels and reshape into rows
        pixels = [ palette[i] for i in result_indices ]

        rows = []
        idx = 0
        for _ in range(height):
            row = []
            for _ in range(width):
                # guard against truncated data
                if idx < len(pixels):
                    row.append(pixels[idx])
                else:
                    row.append((0,0,0))
                idx += 1
            rows.append(row)

        return (rows, width, height, original_size)