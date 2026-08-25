## FR-5: FDX `<DualDialogue>` wrapper

**Request**: emit side-by-side dialogue in Final Draft XML. FR-3 shipped
without it because no accessible sample contained a dual block and Final
Draft is not installed on any development machine, so the XML shape could
not be verified. Fountain already carried the caret, so the information was
never lost; only the FDX rendering of it was missing.

**Blocked on**: a file. Four public FDX samples (`rsdoiel/fdx`
`sample-01`, `-05`, `-06`, plus a spec script) and an XPath reference gist
were checked during FR-3 and none contained dual dialogue. Two libraries
looked at, `rsdoiel/fdx` and `lapingvino/lexington`, do not handle the
element at all and drop the block silently, so their structs were no
evidence either.

**Resolved by** samples supplied by the owner (`FDX_Verification.zip`),
corroborated from screenplain's exporter and afterwriting's FDX *importer*.
The importer matters more than the exporter: it reads genuine Final Draft
output, so the shape is not just one library's house convention.

**The shape**:

```xml
<Paragraph>                       <!-- untyped wrapper, no Text of its own -->
  <DualDialogue>
    <Paragraph Type="Character"><Text>MARA</Text></Paragraph>
    <Paragraph Type="Dialogue"><Text>I am not doing this again.</Text></Paragraph>
    <Paragraph Type="Character"><Text>DELL</Text></Paragraph>
    <Paragraph Type="Dialogue"><Text>You already did.</Text></Paragraph>
  </DualDialogue>
</Paragraph>
```

**The trap, for anyone who later writes a reader**: the wrapper carries no
`Type` and no `<Text>`. Iterating `Content`'s direct children hands back a
typeless paragraph; `.//Paragraph` hands back the four inner ones **plus**
the wrapper, so a naive count double-counts. A reader has to test for a
`DualDialogue` child before reading `Type`. The two speakers are a flat
sequence inside, left column first, not two sibling columns.
`tests/test_export_fdx.py` pins both properties.

**Also established, and worth not re-litigating**: there is no official FDX
XSD or DTD. Final Draft has never published one, so nothing can validate an
FDX in the strict sense. Anything advertising itself as an FDX validator is
doing well-formedness or a round-trip import. Do not go looking for a
schema.

**Sample provenance, noted because it bounds the claim**: all three supplied
samples carry `Version="1"`, which is what screenplain writes, while the two
genuine Final Draft exports verified during FR-3 carry `Version="3"` and
`"4"`. The samples corroborate the *element shape*, which afterwriting's
importer independently confirms against real Final Draft output; they are
not themselves Final Draft exports. The emitter keeps `Version="3"`, taken
from a real export. Opening a generated file in Final Draft itself remains
the FR-3 manual gate.

**Declined**: reconstructing the shape from library source alone, which was
the fallback offered during FR-3 planning. Two of the four libraries
examined get it wrong, so agreement between any two of them would not have
been evidence.
