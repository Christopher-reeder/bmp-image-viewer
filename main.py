# NOTE: For displaying the parsed image in a GUI,
#       please download PyQt5.
#
# Installation (in terminal):
#   pip install PyQt5
import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel,
    QFileDialog, QTextEdit, QSlider, QHBoxLayout, QCheckBox
)
from PyQt5.QtGui import QPixmap, QImage, qRgb
from PyQt5.QtCore import Qt
from bmp_parser import BMPParser
from compressor import BMPCompressor, BMPDecompressor

class BMPViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BMP Viewer")
        self.resize(700, 500)

        # Store original pixel data and image size
        self.original_pixels = None
        self.width = 0
        self.height = 0

        # RGB channels toggle and display settings
        self.r_enabled = True
        self.g_enabled = True
        self.b_enabled = True
        self.brightness = 1.0
        self.scale = 1.0

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()

        # Button to open BMP file
        self.open_button = QPushButton("Open BMP File")
        self.open_button.setFixedSize(150, 50)
        self.open_button.clicked.connect(self.open_file)
        top_layout.addWidget(self.open_button)

        # Button to compress BMP file
        self.compress_button = QPushButton("Compress BMP File")
        self.compress_button.setFixedSize(150, 50)
        self.compress_button.clicked.connect(self.compress_file)
        top_layout.addWidget(self.compress_button)

        # Button to decompress BMP file
        self.decompress_button = QPushButton("Decompress BMP File")
        self.decompress_button.setFixedSize(150, 50)
        self.decompress_button.clicked.connect(self.decompress_file)
        top_layout.addWidget(self.decompress_button)

        top_layout.addStretch()

        # Checkboxes to enable/disable R, G, B channels
        self.r_button = QCheckBox("R")
        self.g_button = QCheckBox("G")
        self.b_button = QCheckBox("B")

        self.r_button.clicked.connect(self.toggle_r)
        self.g_button.clicked.connect(self.toggle_g)
        self.b_button.clicked.connect(self.toggle_b)

        for btn in (self.r_button, self.g_button, self.b_button):
            btn.setChecked(True)
            btn.setFixedSize(30, 30)            
            top_layout.addWidget(btn)

        layout.addLayout(top_layout)

        # Label to display the image
        self.image_label = QLabel("No Image Loaded")
        self.image_label.setStyleSheet("border: 1px solid black; background: white;")
        self.image_label.setAlignment(Qt.AlignCenter)  
        self.image_label.setFixedSize(700, 400)
        layout.addWidget(self.image_label)

        # Text box to display BMP metadata
        self.metadata_box = QTextEdit("No Metadata Loaded")
        self.metadata_box.setMinimumHeight(150)
        self.metadata_box.setReadOnly(True)
        layout.addWidget(self.metadata_box)

        # Slider for brightness adjustment
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.setValue(100)
        self.brightness_slider.valueChanged.connect(self.update_image)
        layout.addWidget(QLabel("Brightness"))
        layout.addWidget(self.brightness_slider)

        # Slider for scaling the image
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(1, 100)
        self.scale_slider.setValue(100)
        self.scale_slider.valueChanged.connect(self.update_image)
        layout.addWidget(QLabel("Scale"))
        layout.addWidget(self.scale_slider)

        self.setLayout(layout)

    # Open BMP file and load pixel data
    def open_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Open BMP File", "", "BMP Files (*.bmp)")
        if not filepath:
            return
        
        parser = BMPParser(filepath)
        parser.load()

        # Display metadata
        meta_text = ""
        for k, v in parser.metadata.items():
            meta_text += f"{k}: {v}\n"
        self.metadata_box.setText(meta_text)

        # Store pixel data and image size
        self.original_pixels = parser.pixel_data
        self.width = parser.metadata["width"]
        self.height = abs(parser.metadata["height"])

        # remember current opened file path so compressor can use real file size
        self.current_filepath = filepath

        self.update_image()

    # Update image display based on settings
    def update_image(self):
        if self.original_pixels is None:
            return

        self.brightness = self.brightness_slider.value() / 100.0
        self.scale = self.scale_slider.value() / 100.0

        new_w = int(self.width * self.scale)
        new_h = int(self.height * self.scale)

        image = QImage(new_w, new_h, QImage.Format_RGB32)

        # Loop through each pixel and apply brightness and RGB toggle
        for y in range(new_h):
            for x in range(new_w):
                src_x = int(x / self.scale)
                src_y = int(y / self.scale)

                R, G, B = self.original_pixels[src_y][src_x]

                if not self.r_enabled:
                    R = 0
                if not self.g_enabled:
                    G = 0
                if not self.b_enabled:
                    B = 0

                R = int(R * self.brightness)
                G = int(G * self.brightness)
                B = int(B * self.brightness)

                image.setPixel(x, y, qRgb(R, G, B))

        # Show updated image
        pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(pixmap)
        
    # Toggle R channel
    def toggle_r(self):
        self.r_enabled = self.r_button.isChecked()
        self.update_image()

    # Toggle G channel
    def toggle_g(self):
        self.g_enabled = self.g_button.isChecked()
        self.update_image()

    # Toggle B channel
    def toggle_b(self):
        self.b_enabled = self.b_button.isChecked()
        self.update_image()

    def compress_file(self):
        if self.original_pixels is None:
            return
        
        output_filepath, _ = QFileDialog.getSaveFileName(self, "save compressed file", "", "CMPT365 Files (*.cmpt365)")
        if not output_filepath:
            return
        
        compressor = BMPCompressor()
        info = compressor.compress(self.original_pixels, output_filepath, self.current_filepath)

        self.metadata_box.append(f"Compressed to {output_filepath}")
        self.metadata_box.append(f"Original size: {info['original_size']} bytes")
        self.metadata_box.append(f"Compressed size: {info['compressed_size']} bytes")
        self.metadata_box.append(f"Compression ratio: {info['ratio']:.3f}")
        self.metadata_box.append(f"Time: {info['time_ms']:.2f} ms")

    def decompress_file(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = BMPViewer()
    viewer.show()
    sys.exit(app.exec_())
