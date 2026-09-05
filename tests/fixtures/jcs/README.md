# RFC 8785 vectors

`rfc8785_number_vectors.json` transcribes the finite IEEE 754 values and their
required JSON representations from RFC 8785 Appendix B. The primary
serialization and property-order examples in `tests/test_canonical.py` come
from RFC 8785 sections 3.2.2 through 3.2.4.

Source: <https://www.rfc-editor.org/rfc/rfc8785.html>

The RFC is published by the IETF Trust. The local tests add rejection and digest
cases specific to Quant Hunter; they are not presented as upstream vectors.
