## 2024-05-30 - copy.deepcopy is extremely slow on deeply nested large structures like lists of dictionaries
**Learning:** `copy.deepcopy` iterates over every element recursively and handles self-references and custom classes overhead, which significantly impacts its performance when iterating on typical dictionaries/lists.
**Action:** When a function's argument is known to only be composed of basic types (lists and dictionaries), writing a custom loop traversing the structure takes a fraction of the time (approx. 4x faster) of calling the standard `copy.deepcopy`.
