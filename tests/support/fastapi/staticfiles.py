from fastapi import _Static


class StaticFiles(_Static):
    def __init__(self, directory=None):
        super().__init__(directory)
