import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel,
    QFileDialog, QTextEdit, QSlider, QHBoxLayout, QCheckBox
)
from PyQt5.QtGui import QPixmap, QImage, qRgb
from PyQt5.QtCore import Qt
from bmp_parser import BMPParser

class BMPViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BMP Viewer")
        self.resize(700, 500)

        self.original_pixels = None
        self.width = 0
        self.height = 0

        self.r_enabled = True
        self.g_enabled = True
        self.b_enabled = True
        self.brightness = 1.0
        self.scale = 1.0

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()

        self.open_button = QPushButton("Open BMP File")
        self.open_button.setFixedSize(120, 50)
        self.open_button.clicked.connect(self.open_file)
        top_layout.addWidget(self.open_button)

        top_layout.addStretch()
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

        self.image_label = QLabel("No Image Loaded")
        self.image_label.setStyleSheet("border: 1px solid black; background: white;")
        self.image_label.setAlignment(Qt.AlignCenter)  
        self.image_label.setFixedSize(700, 400)
        layout.addWidget(self.image_label)

        self.metadata_box = QTextEdit("No Metadata Loaded")
        self.metadata_box.setReadOnly(True)
        layout.addWidget(self.metadata_box)

        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.setValue(100)
        self.brightness_slider.valueChanged.connect(self.update_image)
        layout.addWidget(QLabel("Brightness"))
        layout.addWidget(self.brightness_slider)

        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(1, 100)
        self.scale_slider.setValue(100)
        self.scale_slider.valueChanged.connect(self.update_image)
        layout.addWidget(QLabel("Scale"))
        layout.addWidget(self.scale_slider)

        self.setLayout(layout)

    def open_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Open BMP File", "", "BMP Files (*.bmp)")
        if not filepath:
            return
        
        parser = BMPParser(filepath)
        parser.load()

        meta_text = ""
        for k, v in parser.metadata.items():
            meta_text += f"{k}: {v}\n"
        self.metadata_box.setText(meta_text)

        self.original_pixels = parser.pixel_data
        self.width = parser.metadata["width"]
        self.height = abs(parser.metadata["height"])

        self.update_image()

    def update_image(self):
        if self.original_pixels is None:
            return

        self.brightness = self.brightness_slider.value() / 100.0
        self.scale = self.scale_slider.value() / 100.0

        new_w = int(self.width * self.scale)
        new_h = int(self.height * self.scale)

        image = QImage(new_w, new_h, QImage.Format_RGB32)

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

        pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(pixmap)
        
    def toggle_r(self):
        self.r_enabled = self.r_button.isChecked()
        self.update_image()

    def toggle_g(self):
        self.g_enabled = self.g_button.isChecked()
        self.update_image()

    def toggle_b(self):
        self.b_enabled = self.b_button.isChecked()
        self.update_image()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = BMPViewer()
    viewer.show()
    sys.exit(app.exec_())
