"""
Minimal TF‑IDF + LogisticRegression trainer.

Usage:
  uv run python -m newswire.train_tfidf input.csv output.joblib

CSV schema:
  text,label
Where label is 1 for material, 0 for not.
"""

from __future__ import annotations

import sys

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline


def main():
    if len(sys.argv) < 3:
        print("Usage: python -m newswire.train_tfidf input.csv output.joblib")
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2]
    df = pd.read_csv(inp)
    df = df.dropna(subset=["text", "label"]).reset_index(drop=True)
    X_train, X_test, y_train, y_test = train_test_split(
        df["text"], df["label"], test_size=0.2, random_state=42, stratify=df["label"]
    )
    pipe = Pipeline(
        steps=[
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_df=0.9, min_df=3)),
            ("logreg", LogisticRegression(max_iter=200, class_weight="balanced")),
        ]
    )
    pipe.fit(X_train, y_train)
    y_pred = pipe.predict(X_test)
    print(classification_report(y_test, y_pred))
    joblib.dump(pipe, out)
    print(f"Model saved to {out}")


if __name__ == "__main__":
    main()
