import json
import os
import tempfile
import shutil
import logging
from PyQt6.QtCore import QTimer, QObject, pyqtSignal

logger = logging.getLogger('WhisperNote.autosave')

class AutosaveManager(QObject):
    
    saved = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, delay_ms=2000):
        super().__init__()
        self.delay_ms = delay_ms
        self.last_saved_text = ""
        self.current_filepath = None
        self._get_current_text = None
        
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._do_save)
        
        logger.debug(f"AutosaveManager initialized with delay={delay_ms}ms")
    
    def set_text_getter(self, callback):
        if not callable(callback):
            logger.error("set_text_getter: callback is not callable")
            return
        self._get_current_text = callback
        logger.debug("Text getter callback set")
    
    def set_active_note(self, filepath, initial_text):
        if not filepath:
            logger.warning("set_active_note called with empty filepath")
            return
            
        self.current_filepath = filepath
        self.last_saved_text = initial_text
        self.timer.stop()
        logger.info(f"Active note set: {os.path.basename(filepath)}")
    
    def clear_active_note(self):
        if self.current_filepath:
            logger.info(f"Clearing active note: {os.path.basename(self.current_filepath)}")
        
        self.current_filepath = None
        self.last_saved_text = ""
        self.timer.stop()
    
    def on_text_changed(self):
        if not self.current_filepath:
            logger.debug("on_text_changed: no active note, ignoring")
            return
        
        self.timer.stop()
        self.timer.start(self.delay_ms)
        logger.debug(f"Autosave timer restarted ({self.delay_ms}ms)")
    
    def force_save(self):
        if not self.current_filepath:
            logger.debug("force_save: no active note")
            return
        
        self.timer.stop()
        logger.info("Force save triggered")
        self._do_save()
    
    def _do_save(self):
        if not self.current_filepath:
            logger.warning("_do_save: no current_filepath")
            return
        
        if not self._get_current_text:
            logger.error("_do_save: text getter not set")
            return
        
        try:
            new_text = self._get_current_text().strip()
            
            if new_text == self.last_saved_text:
                logger.debug("Text unchanged, skipping save")
                return
            
            if not new_text:
                logger.debug("Text is empty, skipping save")
                return
            
            if not os.path.exists(self.current_filepath):
                logger.error(f"File does not exist: {self.current_filepath}")
                self.error.emit(f"File does not exist: {os.path.basename(self.current_filepath)}")
                return
            
            logger.debug(f"Loading existing note: {self.current_filepath}")
            with open(self.current_filepath, 'r', encoding='utf-8') as f:
                note_data = json.load(f)
            
            note_data['full_text'] = new_text
            
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.json',
                prefix='autosave_',
                dir=os.path.dirname(self.current_filepath)
            )
            
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(note_data, f, ensure_ascii=False, indent=4)
                
                if os.name == 'nt':
                    os.replace(temp_path, self.current_filepath)
                else:
                    shutil.move(temp_path, self.current_filepath)
                
                self.last_saved_text = new_text
                logger.info(f"Autosaved: {os.path.basename(self.current_filepath)} ({len(new_text)} chars)")
                self.saved.emit(self.current_filepath)
                
            except Exception as e:
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
                raise
        
        except json.JSONDecodeError as e:
            error_msg = f"Error JSON: {str(e)}"
            logger.error(f"Autosave failed - invalid JSON in {self.current_filepath}: {e}", exc_info=True)
            self.error.emit(error_msg)
        
        except PermissionError as e:
            error_msg = f"Permission denied: {os.path.basename(self.current_filepath)}"
            logger.error(f"Autosave failed - permission denied: {e}", exc_info=True)
            self.error.emit(error_msg)
        
        except IOError as e:
            error_msg = f"Error writing: {str(e)}"
            logger.error(f"Autosave failed - I/O error: {e}", exc_info=True)
            self.error.emit(error_msg)
        
        except Exception as e:
            error_msg = f"Unknown error: {str(e)}"
            logger.error(f"Autosave failed - unexpected error: {e}", exc_info=True)
            self.error.emit(error_msg)
