import random
from server_manager import SERVER_CONFIG

def select_server():
    """Initial placement is random across Servers 1, 2 and 3 only."""
    return random.choice((1, 2, 3))
