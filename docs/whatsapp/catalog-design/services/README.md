# Versioned service artwork release

The six editable SVG masters, preview and manifest remain in this directory. The
4096px PNG release payloads are stored under the existing bucket/object keys in
manifest.json rather than duplicated in the source checkout. This externalization
preserves the approved raster bytes; it does not change service availability,
catalog approval, Wix product identity or any customer route.

Each product records imageSha256/imageBytes and its imageKey/imageUrl. The version
segment in a key is a design-release convention, not proof of S3 object immutability.
Verify the complete downloaded bytes against the recorded SHA256 and byte count
before assigning, restoring or relying on a raster object. HTTP200, file extension
and ETag alone are insufficient evidence of equivalence.

The original PNG payloads were preserved outside the repository before removal;
the reviewed externalization evidence records their hashes and remote verification.
Restore a required local PNG as <slug>-4096.png from a byte-verified stored object or
preserved release copy. Do not assume re-rendering an SVG reproduces the exact PNG:
font availability and renderer versions can affect raster output. The localSource
and sourceSha256 fields identify the retained editable masters; previewSha256
identifies the retained preview.

Catalog/Wix assignment and approval remain separate work. Existing remote artwork
objects and their manifest URLs are retained; no frontend image path is changed.
