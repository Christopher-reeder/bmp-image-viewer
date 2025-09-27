class BMPParser:
    def __init__(self, filepath):
        self.filepath = filepath
        self.metadata = {}
        self.pixel_data = []
        self.color_table = []

    def load(self):
        with open(self.filepath, "rb") as f:
            self.bmp_bytes = f.read()
        self._parse_header()
        self._parse_color_table()
        self._parse_pixel_data()

    def _parse_header(self):
        b = self.bmp_bytes
        # Signature
        if b[0:2] != b'BM':
            raise ValueError("Not a BMP file")
        # File size
        self.metadata['file_size'] = int.from_bytes(b[2:6], 'little')
        # Data offset
        self.metadata['data_offset'] = int.from_bytes(b[10:14], 'little')
        # Width & height
        self.metadata['width'] = int.from_bytes(b[18:22], 'little')
        self.metadata['height'] = int.from_bytes(b[22:26], 'little', signed=True)
        # Bits per pixel
        self.metadata['bpp'] = int.from_bytes(b[28:30], 'little')

    def _parse_color_table(self):
        bpp = self.metadata['bpp']
        if bpp in [1, 4, 8]:
            num_colors = 1 << bpp  # 2^bpp
            self.color_table = []

            #dib_header_size = int.from_bytes(self.bmp_bytes[14:18], 'little')
            #start = 14 + dib_header_size
            start = 0x36
            for i in range(num_colors):
                b, g, r, _ = self.bmp_bytes[start + i*4 : start + i*4 + 4]
                self.color_table.append((r, g, b))  # (R, G, B)

    def _parse_pixel_data(self):
        bpp = self.metadata['bpp']
        offset = self.metadata['data_offset']
        width = self.metadata['width']
        height = self.metadata['height']

        row_size = ((bpp * width + 31) // 32) * 4
        self.pixel_data = []
        
        abs_height = abs(height)
        is_bottom_up = height > 0

        for row in range(abs_height):
            row_pixels = []
            if is_bottom_up:
                row_start = offset + (abs_height - row - 1) * row_size
            else:
                row_start = offset + row * row_size

            if bpp == 24:
                for col in range(width):
                    idx = row_start + col * 3
                    B, G, R = self.bmp_bytes[idx:idx+3]
                    row_pixels.append((R,G,B))
            
            elif bpp == 8:
                for col in range(width):
                    color_index = self.bmp_bytes[row_start + col]
                    row_pixels.append(self.color_table[color_index])

            elif bpp == 4:
                for col in range(width):
                    byte  = self.bmp_bytes[row_start + col//2]
                    if col % 2 == 0:
                        index = byte >> 4
                    else:
                        index = byte & 0x0F
                    row_pixels.append(self.color_table[index])

            elif bpp == 1:
                for col in range(width):
                    byte = self.bmp_bytes[row_start + col//8]
                    bit_index = 7 - (col % 8)
                    index = (byte >> bit_index) & 1
                    row_pixels.append(self.color_table[index])

            else:
                raise ValueError(f"Unsupported bpp: {bpp}")
            
            self.pixel_data.append(row_pixels)