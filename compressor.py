import time
import os

class BMPCompressor:

    def __init__(self):
        self.max_dict_size = 4096

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

        # pack codes as 12-bit LSB-first
        packed = bytearray()
        acc = 0
        bits = 0
        for code in codes:
            acc |= (code & 0xFFF) << bits
            bits += 12
            while bits >= 8:
                packed.append(acc & 0xFF)
                acc >>= 8
                bits -= 8
        if bits > 0:
            packed.append(acc & 0xFF)

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
    pass