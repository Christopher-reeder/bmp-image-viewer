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
        codes = self._lzw_on_indices(indices)
        end_time = time.time()

        # pack codes as 16-bit little-endian words (fixed width)
        packed = bytearray()
        for code in codes:
            # append 16-bit little-endian representation of each code
            packed += code.to_bytes(2, 'little')

        # write file: magic + original size + width + height + palette + data
        with open(output_file, 'wb') as f:
            f.write(b"CMPT365")
            f.write(original_size.to_bytes(4, 'big'))
            f.write(width.to_bytes(4, 'big'))
            f.write(height.to_bytes(4, 'big'))
            # palette length (unsigned short)
            f.write(len(palette).to_bytes(2, 'big'))
            for (r, g, b) in palette:
                f.write(bytes([r, g, b]))
            f.write(packed)

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

    def _lzw_on_indices(self, data):

        # initial dictionary contains all single-symbols seen in palette
        dict_size = max(data) + 1 if data else 0
        # Ensure at least 1..256 initial dictionary; but we built palette so dict_size equals palette size
        dictionary = { (i,): i for i in range(dict_size) }

        result = []
        s = (data[0],) if data else ()
        for c in data[1:]:
            sc = s + (c,)
            if sc in dictionary:
                s = sc
            else:
                result.append(dictionary[s])
                if dict_size < self.max_dict_size:
                    dictionary[sc] = dict_size
                    dict_size += 1
                s = (c,)

        if s:
            result.append(dictionary[s])

        return result


class BMPDecompressor:
    def decompress(self, input_file):

        with open(input_file, 'rb') as f:
            data = f.read()

        if not data.startswith(b"CMPT365"):
            raise ValueError("Not a CMPT365 file")

        pos = 7
        original_size = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
        width = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
        height = int.from_bytes(data[pos:pos+4], 'big'); pos += 4
        palette_len = int.from_bytes(data[pos:pos+2], 'big'); pos += 2

        palette = []
        for _ in range(palette_len):
            r = data[pos]; g = data[pos+1]; b = data[pos+2]
            palette.append((r, g, b))
            pos += 3

        packed = data[pos:]

        # unpack 16-bit little-endian codes
        # If packed length is odd, ignore the final partial byte.
        codes = [int.from_bytes(packed[i:i+2], 'little') for i in range(0, len(packed) - (len(packed) % 2), 2)]

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