# each parser implements this API, and should start a gevent loop until finished() is True.
class GameParser():
    def __init__(self, game_path, storage_path):
        self.finished = False
        self.game_path = game_path
        self.storage_path = storage_path
        self.threads = []
        self.errors = []
        return
    # todo, what format should a return value of "changes" give? a tuple of old,new? a 
    def get_changes(self):
        return None
    # todo, 
    def get_result(self):
        return None
