from functools import wraps


def validate_file_directory(file_directory):
    """
    checks that file directory is usable as a data directory

    A blank or whitespace-only value is rejected alongside None: an unset
    environment variable or an empty config field would otherwise resolve to
    the process working directory and read whatever happens to be there.

    :raises: ValueError: If file_directory is None or blank
    """
    if file_directory is None or not str(file_directory).strip():
        raise ValueError("file_directory cannot be None when data source is file")
    return file_directory


def check_file_directory(method):
    """
    decorator to be used on method to load data from file to
    check that file directory is not None

    :raises: ValueError: If file_directory is None or blank
    """

    @wraps(method)
    def decorated_method(self, *method_args, **method_kwargs):
        validate_file_directory(self.file_directory)
        return method(self, *method_args, **method_kwargs)

    return decorated_method
