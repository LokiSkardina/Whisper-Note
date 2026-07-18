# 🎙️ Whisper Note

A simple utility for local audio-to-text transcription powered by OpenAI Whisper. No complex settings — unzip, run, pick a model, get your text.

![Python](https://img.shields.io/badge/Python-3.11-blue) ![Whisper](https://img.shields.io/badge/AI-OpenAI%20Whisper-green) ![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## What it is

<img width="1280" height="764" alt="Image" src="https://github.com/user-attachments/assets/1bf7f832-483e-461d-9477-632792c4068a" />

Whisper Note turns voice or audio files into text using the OpenAI Whisper model, running entirely on your PC. It works with microphone recordings and existing audio files, and lets you copy or download the result as `.txt`.

The main advantage over similar tools isn't a long feature list — it's the clean, minimalist interface: model, language, recording, transcription and download are all on one screen, no extra menus or settings.

---

## Download & run

Archive (~4.99 GB, includes Python, PyTorch with CUDA, and FFmpeg) is hosted on Hugging Face:
**[huggingface.co/fortexe/Whisper-Note](https://huggingface.co/fortexe/Whisper-Note)** → `Whisper-Note-v0.1.1-Windows-x64-portable.7z`

1. Download and extract the archive anywhere convenient.
2. Run `Whisper Note.exe`.
3. Pick a Whisper model (on first launch `tiny` downloads automatically to verify everything works) and a language.
4. Record or load a file — via drag & drop or the file button.

The app doesn't create files outside its own folder — just extract and use.

---

## Model download issues

If a model download fails or shows a checksum/hash mismatch, the downloaded file may be incomplete. Close the app and delete the incomplete model file from the `Whisper Note\models` folder before trying again.

You can also download a model manually from the official OpenAI Whisper model list:

**[Official Whisper model files](https://github.com/openai/whisper/blob/main/whisper/__init__.py)**

Download the `.pt` file for the model you need and place it directly into:

```text
Whisper Note\models
```

For example:

```text
Whisper Note\models\tiny.pt
Whisper Note\models\base.pt
Whisper Note\models\small.pt
Whisper Note\models\medium.pt
Whisper Note\models\turbo.pt
Whisper Note\models\large-v3.pt
```

After that, restart Whisper Note and select the same model in the app.

> Only use the original `.pt` model files for OpenAI Whisper. Files made for other Whisper implementations may not work with this application.

---

## Transcription settings

`core/transcription.py` includes custom prompts for five languages, helping the model keep punctuation and sentence structure on long recordings:

```python
prompts = {
    "ru": "Привет. Это пример текста, записанного с хорошей пунктуацией. Здесь есть запятые, точки, дефисы — всё как положено. Текст разбит на предложения.",
    "en": "Hello. This is a sample text with proper punctuation. It includes commas, periods, and hyphens. The text is divided into sentences.",
    "de": "Hallo. Dies ist ein Beispieltext mit korrekter Zeichensetzung. Er enthält Kommas, Punkte und Bindestriche.",
    "fr": "Bonjour. Ceci est un exemple de texte avec une ponctuation correcte. Il comprend des virgules, des points et des tirets.",
    "es": "Hola. Este es un texto de ejemplo con puntuación adecuada. Incluye comas, puntos y guiones."
}
```

Default transcription parameters:

```python
transcribe_options = {
    "task": "transcribe",
    "temperature": 0.2,
    "condition_on_previous_text": True,
    "no_speech_threshold": 0.6,
    "logprob_threshold": -1.0,
    "compression_ratio_threshold": 2.4
}
```

These values are set intentionally: they help the model preserve punctuation and spelling on long, complex recordings even on weaker hardware, at the cost of a higher chance of hallucinations during silence or noise. It's a deliberate trade-off — the result stays readable, and any stray hallucinated text at the end can be deleted or skipped in a second.

---

## Performance Benchmarks

Time to transcribe a **10-minute (630s)** English audio file.
*Lower is better.*

| Model     | RTX 4070 Laptop | RTX 2070 Super | Notes                                |
| --------- | --------------- | -------------- | ------------------------------------ |
| tiny      | 00:15 (42.0x)   | 00:20 (31.5x)  | Blazing fast, lowest accuracy        |
| tiny.en   | 00:20 (31.5x)   | 00:19 (33.2x)  | Fastest model available              |
| base      | 00:19 (33.1x)   | 00:25 (25.2x)  | Very fast, standard baseline         |
| base.en   | 00:22 (28.6x)   | 00:26 (24.2x)  | Optimized for English, very fast     |
| small     | 00:33 (19.1x)   | 00:44 (14.3x)  | Good speed/accuracy trade-off        |
| small.en  | 00:35 (18.0x)   | 00:44 (14.3x)  | Balanced choice for English          |
| medium    | 03:02 (3.5x)    | 03:47 (2.8x)   | Heavy load, significantly slower     |
| medium.en | 01:00 (10.5x)   | 01:17 (8.2x)   | Great balance for English tasks      |
| turbo     | 02:00 (5.25x)   | 03:33 (3.0x)   | High accuracy, moderate speed        |
| large-v3  | 08:51 (1.2x)    | 17:29 (0.6x)   | Slower than real-time, max precision |

*(English-only models `.en` are slightly faster for English audio. Tests were performed on Windows 11, CUDA enabled, using the same 630s audio file.)*

---

## Known Limitations

**Repeated phrases or extra text at the end.** These are Whisper hallucinations that occur during silence or background noise — the trade-off for settings that preserve punctuation on long recordings (see above). Just delete that text manually, takes a second.

**Can't stop transcription mid-process.** Once started, the process has to finish — no cancel button yet.

---

## Stack

Whisper (OpenAI) · PyQt6 · PyAudio / PyDub / FFmpeg · PyTorch (CUDA)

**License:** MIT — free to use and modify.
