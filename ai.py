"""
ai.py -- AI feature module for KindlePi.

Communicates with the local llama.cpp server running on port 8080.
All calls are synchronous -- reader.py shows a loading screen before calling.

Features:
    - Chapter summary: summarise the chapter text so far
    - Ask a question: answer a free-text question in the context of the chapter
"""

import json
import urllib.request
import urllib.error

LLAMA_URL     = "http://localhost:8080/v1/chat/completions"
MODEL         = "qwen2.5-1.5b-instruct-q4_k_m"
MAX_TOKENS    = 300
TIMEOUT_SECS  = 60
CONTEXT_CHARS = 4000


class AIError(Exception):
    pass


class AIClient:
    def __init__(self, url: str = LLAMA_URL):
        self.url = url

    def chapter_summary(
        self,
        chapter_text: str,
        previous_summary: str | None = None
    ) -> str:
        """
        Summarise the chapter text in 3-5 sentences.
        If previous_summary is provided, it's included as rolling context
        so the model understands what happened before this chapter.
        """
        context = self._truncate(chapter_text)
        prev_block = ""
        if previous_summary:
            prev_block = (
                f"Previous chapter summary:\n{previous_summary}\n\n"
            )
        prompt = (
            "You are a reading assistant on an e-ink device. "
            "Summarise the following chapter excerpt in 3-5 clear sentences. "
            "Be concise -- the reader wants a quick recap, not analysis.\n\n"
            f"{prev_block}"
            f"Current chapter:\n{context}"
        )
        return self._call(prompt)

    def ask_question(
        self,
        chapter_text: str,
        question: str,
        previous_summary: str | None = None
    ) -> str:
        """
        Answer a question in the context of the chapter text.
        """
        context   = self._truncate(chapter_text)
        prev_block = ""
        if previous_summary:
            prev_block = (
                f"Previous chapter summary:\n{previous_summary}\n\n"
            )
        prompt = (
            "You are a reading assistant on an e-ink device. "
            "Answer the following question based on the chapter excerpt. "
            "Be concise -- 2-4 sentences maximum.\n\n"
            f"{prev_block}"
            f"Current chapter:\n{context}\n\n"
            f"Question: {question}"
        )
        return self._call(prompt)

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(
                "http://localhost:8080/health",
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            return False

    def _call(self, prompt: str) -> str:
        payload = json.dumps({
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": MAX_TOKENS,
            "temperature": 0.7,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except urllib.error.URLError as e:
            raise AIError(f"Cannot reach llama.cpp server: {e}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise AIError(f"Unexpected response from llama.cpp: {e}")

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) <= CONTEXT_CHARS:
            return text
        return text[:CONTEXT_CHARS] + "\n\n[Text truncated for length]"


if __name__ == "__main__":
    client = AIClient()
    print("Checking llama.cpp server...")
    if not client.is_available():
        print("ERROR: llama.cpp server not reachable on port 8080.")
        raise SystemExit(1)

    print("Server reachable. Running rolling context summary test...")
    sample = """
    It is a truth universally acknowledged, that a single man in possession
    of a good fortune, must be in want of a wife. Mr. Bennet was among the
    earliest of her neighbours in calling upon Mr. Bingley.
    """
    prev = "This is the opening of Pride and Prejudice by Jane Austen."
    try:
        result = client.chapter_summary(sample, previous_summary=prev)
        print("\n--- Summary ---")
        print(result)
        print("\nai.py smoke test passed.")
    except AIError as e:
        print(f"ERROR: {e}")
