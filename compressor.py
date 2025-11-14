import time
import os


class BMPCompressor:

    def __init__(self):
        # allow larger palettes by increasing dictionary size to 65536
        self.max_dict_size = 65536

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
        # produce bit-packed LZW payload (variable code width) without external libraries
        packed_payload = self._lzw_pack_indices_to_bits(indices)
        end_time = time.time()

        # write file: magic + version + original size + width + height + palette + data
        with open(output_file, 'wb') as f:
            f.write(b"CMPT365")
            # version byte (2 = variable-bit LZW format)
            f.write(bytes([2]))
            f.write(original_size.to_bytes(4, 'big'))
            f.write(width.to_bytes(4, 'big'))
            f.write(height.to_bytes(4, 'big'))
            # palette length (unsigned int)
            f.write(len(palette).to_bytes(4, 'big'))
            for (r, g, b) in palette:
                f.write(bytes([r, g, b]))
            # write payload length (4 bytes big-endian) and payload
            f.write(len(packed_payload).to_bytes(4, 'big'))
            f.write(packed_payload)

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
        if version != 2:
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

        # read payload length and payload
        if pos + 4 > len(data):
            raise ValueError("Corrupt file: missing payload length")
        payload_len = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
        if pos + payload_len > len(data):
            raise ValueError("Corrupt file: truncated payload")
        packed = data[pos:pos+payload_len]

        # bit-level LZW decode (LSB-first)
        def read_codes_from_bits(packed_bytes, init_dict_size):
            bit_buf = 0
            bit_count = 0
            byte_pos = 0

            def read_bits(n):
                nonlocal bit_buf, bit_count, byte_pos
                while bit_count < n:
                    if byte_pos < len(packed_bytes):
                        bit_buf |= packed_bytes[byte_pos] << bit_count
                        byte_pos += 1
                        bit_count += 8
                    else:
                        # not enough bits
                        return None
                mask = (1 << n) - 1
                val = bit_buf & mask
                bit_buf >>= n
                bit_count -= n
                return val

            dict_size = init_dict_size
            code_width = max(1, (dict_size - 1).bit_length())

            # read first code
            first = read_bits(code_width)
            if first is None:
                return []
            codes = [first]

            while True:
                # adjust code width if needed (note: code_width may have been increased when dict_size crossed boundary)
                if dict_size == (1 << code_width):
                    code_width += 1

                code = read_bits(code_width)
                if code is None:
                    break
                codes.append(code)
                # we cannot know about dict growth here precisely; growth happens during decode loop
                dict_size += 1
                if dict_size >= 65536:
                    dict_size = 65536

            return codes

        # convert packed bits to codes
        init_dict_size = palette_len if palette_len > 0 else 0
        codes = read_codes_from_bits(packed, init_dict_size)

        # LZW decompression on integer symbols
        dict_size = len(palette)
        dictionary = { i: (i,) for i in range(dict_size) }
        max_dict_size = 65536

        result_indices = []
        if not codes:
            # empty payload -> return blank image rows
            rows = [ [ (0,0,0) for _ in range(width) ] for _ in range(height) ]
            return (rows, width, height, original_size)

        prev_code = codes[0]
        # prev_code should be in dictionary
        if prev_code not in dictionary:
            raise ValueError("Corrupt compressed data: first code invalid")
        result_indices.extend(dictionary[prev_code])

        for code in codes[1:]:
            if code in dictionary:
                entry = dictionary[code]
            elif code == dict_size:
                entry = dictionary[prev_code] + (dictionary[prev_code][0],)
            else:
                raise ValueError("Bad compressed code")

            result_indices.extend(entry)

            # add new sequence to dictionary
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