"""DO NOT MERGE -- throwaway file, part of a verification test."""


def read_file_contents(path: str) -> str:
    """Read and return the contents of the file at `path`."""
    f = open(path)
    return f.read()
