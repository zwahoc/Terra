"""One local worker; SQL current-scope CAS also protects multiple processes."""
import logging
import os
import threading
from backend.app.services.matching_service import MatchingService
from backend.app.services.automatic_impact_service import AutomaticImpactService

class MatchingWorker:
    def __init__(self):
        self.stop_event=threading.Event()
        self.thread=None
    def start(self):
        if os.environ.get('TERRA_AUTOMATCH_ENABLED','1')=='0':return
        def work():
            while not self.stop_event.is_set():
                try:MatchingService().refresh()
                except Exception as exc:
                    logging.getLogger(__name__).warning('Matching refresh postponed: %s',type(exc).__name__)
                try:AutomaticImpactService().refresh()
                except Exception as exc:
                    logging.getLogger(__name__).warning('Impact refresh postponed: %s',type(exc).__name__)
                self.stop_event.wait(3)
        self.thread=threading.Thread(target=work,name='terra-matching',daemon=True)
        self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)
