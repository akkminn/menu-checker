from myanmartools import ZawgyiDetector
from myanmar.converter import convert

_detector = ZawgyiDetector()


def normalize_burmese(text: str) -> str:
    """Detect Zawgyi encoding and convert to Unicode if needed."""
    if not text:
        return text
    score = _detector.get_zawgyi_probability(text)
    if score > 0.9:
        return convert(text, 'zawgyi', 'unicode')
    return text
