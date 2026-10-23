"""Converte o PNG aprovado em ICO Windows com múltiplos tamanhos, sem redesenho."""
from pathlib import Path
import struct


def create_icon(source: Path, target: Path):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage
    image = QImage(str(source))
    if image.isNull():
        raise ValueError('O ícone PNG do MockAíZé não pôde ser lido.')
    frames = []
    sizes = (16, 24, 32, 48, 64, 128, 256)
    for size in sizes:
        frame = image.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not frame.save(buffer, 'PNG'):
            raise ValueError('Não foi possível converter o ícone.')
        buffer.close()
        frames.append(bytes(data))
    offset = 6 + 16 * len(sizes)
    directory = bytearray(struct.pack('<HHH', 0, 1, len(sizes)))
    for size, frame in zip(sizes, frames):
        directory.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    target.write_bytes(directory + b''.join(frames))


if __name__ == '__main__':
    assets = Path(__file__).resolve().parents[1] / 'src' / 'mockaize_api' / 'assets'
    create_icon(assets / 'mockaize-favicon.png', assets / 'mockaize.ico')
