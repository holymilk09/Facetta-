# Expectation-free center-prong audit

The validated specification requires six center prongs. A spec-aware vision
audit incorrectly described the saved reference as a six-prong basket. A
second count received only the image, no expected count, and found four
complete center-holding prongs. Deterministic comparison therefore rejects the
render (`4 != 6`).

This is diagnostic evidence, not release evidence. It confirms that the blind
count prevents this known evaluator false negative from reaching an active
revision.
