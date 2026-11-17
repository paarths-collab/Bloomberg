import re
from typing import Dict, Any, List, Tuple

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?;\n]+")
_NEGATORS = {"not", "no", "never", "dont", "don't", "wont", "won't", "isnt", "isn't",
             "wasnt", "wasn't", "arent", "aren't", "didnt", "didn't", "cant", "can't",
             "couldnt", "couldn't", "wouldnt", "wouldn't", "shouldnt", "shouldn't", "without"}
NEGATION_WINDOW = 3  # negator within this many tokens before the keyword neutralises it


def _is_negator(token: str) -> bool:
    return token in _NEGATORS or token.endswith("n't")


class EmotionAnalysisAgent:
    """
    Analyzes user text to detect emotional biases and intensity.
    Used by EmotionAdvisor and MarketPulse.

    This is a keyword HEURISTIC, not a trained model: keywords match whole tokens/phrases
    (not substrings) and a keyword preceded by a negator (not/no/never/n't...) within
    ``NEGATION_WINDOW`` tokens in the same sentence is neutralised.
    """

    # Simple keyword-based bias detection
    BIAS_KEYWORDS = {
        "panic_selling": ["panic", "terrified", "losing all", "sell everything", "crash", "sell all", "dump", "crashing", "scared", "fear", "plunge", "collapse"],
        "fomo_buying": ["moon", "rocket", "miss out", "fomo", "all in", "yolo", "skyrocket", "flying"],
        "overconfidence": ["guaranteed", "sure thing", "easy money", "cannot lose", "safe bet"],
        "revenge_trading": ["make it back", "recover loss", "get even", "revenge", "makeup"]
    }

    EMOTION_INTENSITY_MAP = {
        "panic_selling": 0.8,
        "fomo_buying": 0.7,
        "overconfidence": 0.6,
        "revenge_trading": 0.9
    }

    def analyze(self, message: str) -> Dict[str, Any]:
        """
        Analyze the text for emotional cues.
        Returns a dictionary with intensity, label, and detected biases.
        """
        message = (message or "").lower()
        sentences = [
            _TOKEN_RE.findall(chunk) for chunk in _SENTENCE_SPLIT_RE.split(message)
        ]
        sentences = [tokens for tokens in sentences if tokens]
        negated: List[str] = []

        detected_biases = []
        max_intensity = 0.0
        dominant_bias = None
        
        for bias, keywords in self.BIAS_KEYWORDS.items():
            hits = []
            for w in keywords:
                kw_tokens = _TOKEN_RE.findall(w)
                found, was_negated = self._match(kw_tokens, sentences)
                if found:
                    hits.append(w)
                elif was_negated:
                    negated.append(w)
            if hits:
                score = self.EMOTION_INTENSITY_MAP.get(bias, 0.5)
                # Boost score slightly if multiple keywords found
                if len(hits) > 1:
                    score = min(1.0, score + 0.1)
                
                detected_biases.append({
                    "bias": bias,
                    "score": score,
                    "keywords": hits
                })
                
                if score > max_intensity:
                    max_intensity = score
                    dominant_bias = bias
        
        # Determine label based on intensity and dominant bias
        emotion_label = "calm"
        if max_intensity >= 0.7:
            emotion_label = "highly_emotional"
            if dominant_bias == "panic_selling": emotion_label = "anxious"
            elif dominant_bias == "fomo_buying": emotion_label = "excited"
            elif dominant_bias == "overconfidence": emotion_label = "confident"
        elif max_intensity >= 0.4:
            emotion_label = "concerned" if dominant_bias == "panic_selling" else "optimistic"

        return {
            "text": message,
            "emotion_intensity": max_intensity,
            "emotion_label": emotion_label,
            "dominant_bias": dominant_bias,
            "biases": detected_biases,
            "is_emotional": max_intensity >= 0.5,
            "negated_keywords": negated,
            "method": "keyword_heuristic",
        }

    @staticmethod
    def _match(kw_tokens: List[str], sentences: List[List[str]]) -> Tuple[bool, bool]:
        """Return (found un-negated, found only negated) for a keyword token sequence."""
        n = len(kw_tokens)
        negated_seen = False
        for tokens in sentences:
            for i in range(len(tokens) - n + 1):
                if tokens[i:i + n] != kw_tokens:
                    continue
                window = tokens[max(0, i - NEGATION_WINDOW):i]
                if any(_is_negator(t) for t in window):
                    negated_seen = True
                    continue
                return True, False
        return False, negated_seen
