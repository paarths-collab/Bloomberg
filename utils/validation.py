# check if news is true (fact-checking layer)
'''
Here are 3 strategies you can add:

1.Source Reliability Scoring

Predefine “trusted sources” (Reuters, Bloomberg, Moneycontrol, WSJ, etc.)

Score them higher vs random blogs.

2.Cross-Verification

If the same news appears in multiple trusted outlets → higher reliability.

Example: If Reuters + Bloomberg both publish, assign confidence = 0.9.

3.AI Fact-Check

Use an NLP model (Hugging Face or LangChain’s fact-checking chains) to detect misinformation.

Example: Compare claim against knowledge base (Wikipedia API, DBpedia, or OpenBB news dataset).'''