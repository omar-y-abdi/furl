## 2024-05-24 - [Avoid `copy.deepcopy` when iterating through list of dicts on high volume JSON]
**Learning:** `copy.deepcopy` has very large overhead when copying arrays of dictionaries because of memoization mechanisms.
**Action:** Implementing a recursive Python type check specifically for strings/ints/lists/dicts achieves ~10-20x speedup while satisfying deep duplication logic. Use this when iterating over basic data structures if speed is a constraint.
