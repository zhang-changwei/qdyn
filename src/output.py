from typing import List

class Output:

    def __init__(self):
        self.stdout: List[str] = []
        self.files: List[str] = []
        self.images: List[str] = []

    def merge(self, output: 'Output'):
        """Merge another :class:`~.output.Output` into this one by concatenating
        their lists of stdout lines, files, and images."""
        self.stdout.extend(output.stdout)
        self.files.extend(output.files)
        self.images.extend(output.images)
    