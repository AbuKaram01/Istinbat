# Istinbat (استنباط)

Ask questions about your Arabic and English books and get answers drawn from their text, entirely offline.

It runs on Linux and on Windows 10/11.

## Installation

Supported systems: Debian and Ubuntu (and derivatives), Fedora, Arch Linux (and derivatives such as
Manjaro, EndeavourOS and CachyOS), and Windows 10/11 (64-bit). Each has a one-command installer for a checkout
and a ready-made package or installer.

### Debian / Ubuntu

```bash
./scripts/install-debian.sh          # CPU-only PyTorch (small download)
./scripts/install-debian.sh --cuda   # regular PyTorch and a CUDA build of llama.cpp
```

### Arch Linux

```bash
./scripts/install-arch.sh            # PyTorch from the repositories (CPU)
./scripts/install-arch.sh --cuda     # python-pytorch-cuda and a CUDA build of llama.cpp
```

Both installers set up the system packages, create `.venv`, install the Python dependencies (llama.cpp is
compiled from source, which takes a few minutes), and add an applications-menu entry and icon for your user.

### Windows 10 / 11 (64-bit)

The ready-made installer (`istinbat-<version>-windows-setup.exe`, built by CI and kept as the `istinbat-windows-setup`
artifact of every run) carries everything the program needs: the GTK 4 and libadwaita runtime, Python 3.14, every
Python library (PyTorch, ChromaDB, sentence-transformers, llama.cpp ...) and the Visual C++ runtime. It installs for
your user only, needs no administrator rights and no internet connection; only the models are downloaded later (see
below). That is why the file is large. Installing over an older version keeps your books, models, index and
conversations.

From a checkout, a script makes the same installation and downloads the parts that the installer would have carried:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1          # CPU-only PyTorch, prebuilt llama.cpp
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -Cuda    # llama.cpp compiled with CUDA
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -TorchIndexUrl https://download.pytorch.org/whl/cu128
                                                                              # a CUDA build of PyTorch
```

Build the installer yourself with `powershell -File packaging\build-windows.ps1` (needs Python 3.14, Inno Setup and
internet access for the parts it puts inside).

### Packages

```bash
# Debian, Ubuntu and Fedora packages. Needs dpkg-deb and rpmbuild on the build machine.
./packaging/build.sh
sudo apt install ./packaging/dist/istinbat_0.1.0_amd64.deb          # or istinbat-cuda_...
sudo dnf install ./packaging/dist/istinbat-0.1.0-1.x86_64.rpm       # or istinbat-cuda-...

# Arch packages. Run on an Arch-based system as a normal user.
./packaging/build-arch.sh
sudo pacman -U packaging/dist/istinbat-0.1.0-1-any.pkg.tar.zst      # or istinbat-cuda-...
```

### First launch

When no models are installed yet, the first start opens a **Welcome Guide** with three pages: what Istinbat does,
the download rows for the three models (embedding, reranking and language), and a summary of what is still
missing. Pick the models you want and press **Download**; closing the guide does not stop a download. The guide
opens again from the main menu (**Welcome Guide**) whenever you want it. If you already have the models, skip
the step and point the fields in **Preferences** at them instead.

Nothing is loaded when the window opens. The models load the first time they are needed (your first question,
or **Index** on the Library page), with a progress page while they do. If they cannot be loaded, the error page
explains why, offers **Download Models…** and **Open Preferences**, and **Back** returns to the conversation.
Then set your books folder, add `.txt` books on the **Library** page and press **Index**.

### Downloading models

| Model | Source | Download |
|---|---|---|
| Embedding model | `BAAI/bge-m3` | about 2.3 GB |
| Reranking model | `BAAI/bge-reranker-v2-m3` | about 2.3 GB |
| Language model, Gemma E2B | `unsloth/gemma-4-E2B-it-GGUF` | Q4_K_XL 3.2 GB, Q6_K_XL 4.7 GB, Q8_K_XL 5.3 GB |
| Language model, Gemma E4B | `unsloth/gemma-4-E4B-it-GGUF` | Q4_K_XL 5.1 GB, Q6_K_XL 7.5 GB, Q8_K_XL 8.7 GB |

- The list is fixed in `core/catalog.py`; the application downloads only those files, from those repositories,
  over HTTPS (a redirect that leaves HTTPS is refused). Only the files needed to run a model are fetched.
- Files go to `~/.local/share/istinbat/models/` unless you change **Download folder**. A file is renamed into place
  only when complete, so an interrupted download (or **Stop**) continues where it stopped when you press Download again.
  Short connection drops are retried automatically.
- A finished download becomes the selected model. Models already on disk show **Use** instead, so you can switch
  between quantizations; the choice takes effect the next time the models load (press **Reload models** if they
  are already loaded).
- A download runs in the background: you can keep asking questions, and closing Preferences does not stop it.
- Integrity is checked by size (and llama.cpp validates a GGUF file when it loads it).

## Requirements

- Python 3.10+
- GTK 4.14+ and libadwaita 1.5+ (Ubuntu 24.04 LTS or newer, Debian 13 or newer, Fedora 40 or newer, Arch, or the
  gvsbuild runtime on Windows 10/11 64-bit)
- A GGUF language model, a bge-m3 embedding model and a bge-reranker-v2-m3 model (all downloadable from inside the app)

## Security

A book can contain sentences written for the language model ("ignore your instructions and ..."), and a
question can try the same. No prompt can make a small model obey rules with certainty, so Istinbat does not rely
on the prompt alone. Defences are layered, and each layer is tested without a model (`tests/test_safety.py`,
`tests/test_engine_security.py`):

1. **Untrusted text is neutralized** before it enters a prompt: chat-template control tokens (`<start_of_turn>`,
   `<|im_start|>`, `[INST]`, ...), role tags and look-alikes of our own delimiters lose their brackets, and
   invisible or direction-spoofing characters (including Unicode "tag" characters that hide text) are removed.
   This covers book passages, the question, earlier turns and the rewritten question.
2. **Per-request secrets:** the delimiters around the sources and the question carry a random suffix that a book
   cannot guess, so it cannot close its own block early. A confidential canary token lives only in the system prompt.
3. **A strict system prompt:** the rules come first, declare everything else to be untrusted data, forbid role
   changes, general-chatbot behaviour, revealing the rules and inventing links, and allow exactly one refusal
   sentence. A short reminder repeats the essentials after the untrusted content, where models weigh it most.
4. **The answer is checked before it is shown or stored:** an answer that repeats the canary, a delimiter name, a
   whole line of the rules, or any six consecutive words of them is withheld (and never enters the history);
   invisible characters are stripped; links and images whose address is not written in the sources or the
   question are removed. The interface never makes a link clickable while an answer is still streaming.
5. **Rendering is passive:** raw HTML is never interpreted, images are shown as their alt text, and only
   `http`, `https` and `mailto` links can be opened.

Questions longer than `retrieval.max_question_chars` (4000) are cut.

### Measuring it with your own model

The tests prove the code; only the real model can show whether it obeys a hostile sentence. Run the attack suite
(25 attacks in Arabic and English plus three normal questions, so a prompt that refuses everything is caught too).
Run it from a source checkout, using the virtual environment the application installed:

```bash
/opt/istinbat/venv/bin/python scripts/injection_check.py                  # about 15-30 minutes on a laptop CPU
                                                                          # (Windows: .venv\Scripts\python.exe scripts\injection_check.py)
/opt/istinbat/venv/bin/python scripts/injection_check.py --runs 3 --json report.json
/opt/istinbat/venv/bin/python scripts/injection_check.py --filter extract  # one family of attacks
```

Every attack gets two verdicts: whether the *model alone* resisted, and whether what *you would see* is safe.
The exit status is 1 if any attack reached the user or a normal question was refused. Run it after changing
`core/prompts.py` or the model file.

### Known limits

- This reduces the risk; it cannot remove it. A model can still be talked into a wrong or misleading *answer*.
- The leak check finds verbatim copies, not paraphrases of the rules (a paraphrase reveals little, but it is not blocked).
- A link that is literally written in a book can be repeated by the model. Only addresses that no source contains
  are removed.
- Streaming shows the model's words as they arrive; if the final check withholds the answer, the text already shown
  is replaced by a notice.
- Everything runs locally, so a successful injection cannot send your data anywhere; the realistic damage is a
  misleading answer or a link you choose not to click.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
