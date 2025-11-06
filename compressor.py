import time

class BMPCompressor:
    def __init__(self):
        self.max_dict_size = 4096

    def compress(self, pixel_data, output_file):
        flat_data = []
        for row in pixel_data:
            for R, G, B in row:
                flat_data.extend([R, G, B])

        original_size = len(flat_data) 

        start_time = time.time()
        compressed_data = self.lzw_compress(flat_data)
        end_time = time.time()

        with open(output_file, 'wb') as f:
            f.write(b"CMPT365")
            f.write(original_size.to_bytes(4, 'big'))
            for code in compressed_data:
                f.write(code.to_bytes(2, byteorder='big'))

        compressed_size = len(compressed_data)
        ratio = compressed_size / original_size
        time_ms = (end_time - start_time) * 1000

        return {
            "original_size": original_size,
            "compressed_size": compressed_size,
            "ratio": ratio,
            "time_ms": time_ms
        }

    def lzw_compress(self, data):
        dict_size = 256
        dictionary = {bytes([i]): i for i in range(dict_size)}

        s = b""
        result = []

        for byte in data:
            c = bytes([byte])
            sc = s + c
            if sc in dictionary:
                s = sc
            
            else:
                result.append(dictionary[s])
                if dict_size < self.max_dict_size:
                    dictionary[sc] = dict_size
                    dict_size += 1
                s = c
            
        if s:
            result.append(dictionary[s])

        return result

class BMPDecompressor:
    pass