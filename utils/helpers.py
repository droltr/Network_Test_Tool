def validate_ip(ip):
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or not 0 <= int(part) <= 255:
            return False
    return True

def format_output(data):
    return "\n".join(f"{key}: {value}" for key, value in data.items())

def is_valid_port(port):
    return isinstance(port, int) and 0 <= port <= 65535

def log_message(message):
    # Per-user state directory, not the working directory (read-only in an installed build)
    from utils.paths import log_file_path
    with open(log_file_path("network_tools.log"), "a", encoding="utf-8") as log_file:
        log_file.write(f"{message}\n")