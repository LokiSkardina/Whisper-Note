import pyaudio
import threading
import wave
import time
import logging
import uuid
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger('WhisperNote.recorder')

class AudioRecorder(QObject):
    
    recording_finished = pyqtSignal(object)
    recording_failed = pyqtSignal(str)

    def __init__(self, output_filename="temp_record.wav"):
        super().__init__()
        self.output_filename = output_filename
        
        self.chunk = 1024
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000
        
        self.sample_width = 2
        try:
            p = pyaudio.PyAudio()
            self.sample_width = p.get_sample_size(self.format)
            p.terminate()
        except Exception as e:
            logger.warning(f"Could not determine sample width, using default 2: {e}")
        
        self.frames = []
        self._is_recording = False
        self._is_paused = False
        self._thread = None
        self._lock = threading.Lock()
        self.session_id = None
        
        logger.debug("AudioRecorder initialized")

    def start_recording(self):
        with self._lock:
            if self._is_recording:
                logger.warning("Recording already in progress")
                return
            
            self._is_recording = True
            self._is_paused = False
            self.frames = []
            self.session_id = str(uuid.uuid4())[:8]
        
        logger.info(f"Starting recording thread [session: {self.session_id}]")
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def pause_recording(self):
        with self._lock:
            if not self._is_recording:
                logger.warning(f"Cannot pause - not recording [session: {self.session_id}]")
                return
            self._is_paused = True
        logger.info(f"Recording paused [session: {self.session_id}]")

    def resume_recording(self):
        with self._lock:
            if not self._is_recording:
                logger.warning(f"Cannot resume - not recording [session: {self.session_id}]")
                return
            self._is_paused = False
        logger.info(f"Recording resumed [session: {self.session_id}]")

    def stop_recording(self):
        with self._lock:
            if not self._is_recording:
                return
            self._is_recording = False
        logger.info(f"Recording stopped (no finalization) [session: {self.session_id}]")

    def manual_stop(self):
        with self._lock:
            if not self._is_recording:
                logger.warning(f"manual_stop: not recording [session: {self.session_id}]")
                return
            
            logger.info(f"manual_stop called - setting flag to stop [session: {self.session_id}]")
            self._is_recording = False

    def is_recording(self):
        with self._lock:
            return self._is_recording

    def is_paused(self):
        with self._lock:
            return self._is_paused

    def _record_loop(self):
        p = None
        stream = None
        frames_written = 0
        session = self.session_id
        error_occurred = False
        try:
            logger.debug(f"Opening PyAudio stream [session: {session}]")
            p = pyaudio.PyAudio()
            stream = p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )
            logger.info(f"Recording loop started [session: {session}]")
            while self.is_recording():
                if self.is_paused():
                    time.sleep(0.1)
                    continue
                try:
                    data = stream.read(self.chunk, exception_on_overflow=False)
                    if len(data) == 0:
                        logger.warning(f"Microphone sent 0 bytes, stream might be dead [session: {session}]")
                        time.sleep(0.1)
                        continue
                    with self._lock:
                        self.frames.append(data)
                        frames_written += 1
                    if frames_written % 100 == 0:
                        logger.debug(f"Frames recorded: {frames_written} [session: {session}]")
                except OSError as e:
                    logger.error(f"Critical OSError during recording [session: {session}]: {e}", exc_info=True)
                    with self._lock:
                        self._is_recording = False
                    filepath = self._save_to_file_safely(session)
                    self.recording_failed.emit(filepath)
                    error_occurred = True
                    return
                except Exception as e:
                    logger.error(f"Unexpected error in recording loop [session: {session}]: {e}", exc_info=True)
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"Fatal error opening audio stream [session: {session}]: {e}", exc_info=True)
            self.recording_failed.emit(None)
            error_occurred = True
            return
        finally:
            if stream:
                try:
                    logger.debug(f"Stopping stream [session: {session}]")
                    stream.stop_stream()
                    stream.close()
                except Exception as e:
                    logger.error(f"Error closing stream [session: {session}]: {e}")
            if p:
                try:
                    p.terminate()
                except Exception as e:
                    logger.error(f"Error terminating PyAudio [session: {session}]: {e}")
            logger.info(f"Recording loop finished, total frames: {frames_written} [session: {session}]")
            if not error_occurred:
                filepath = self._save_to_file_safely(session)
                if filepath:
                    logger.info(f"Recording finalized successfully: {filepath} [session: {session}]")
                    self.recording_finished.emit(filepath)
                else:
                    logger.error(f"Recording finalization failed - no file saved [session: {session}]")
                    self.recording_finished.emit(None)

    def _save_to_file_safely(self, session=None):
        with self._lock:
            frames_copy = self.frames[:]
            frame_count = len(frames_copy)
        
        if not frames_copy:
            logger.warning(f"No frames to save [session: {session}]")
            return None
            
        logger.info(f"Saving {frame_count} frames to {self.output_filename} [session: {session}]")
        
        try:
            with wave.open(self.output_filename, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.sample_width)
                wf.setframerate(self.rate)
                wf.writeframes(b''.join(frames_copy))
            
            logger.info(f"File saved successfully: {self.output_filename} [session: {session}]")
            return self.output_filename
        except Exception as e:
            logger.error(f"Error saving audio file [session: {session}]: {e}", exc_info=True)
            return None