#!/bin/bash
# Configura QZ Tray para aceitar o certificado do Accon (portal.accon.ai)
# Uso: bash setup_qztray_accon.sh

pkill -f qz-tray 2>/dev/null || true
sleep 1

echo "Gerando certificado do Accon..."
python3 - << 'PYEOF'
import base64, textwrap

# Certificado do Accon extraído da conexão com QZ Tray
cert_lines = [
    "MIIFDzCCAvegAwIBAgIQNzkyMDI1MTEyNDEyNDQzMDANBgkqhkiG9w0BAQ0FADCB",
    "mDELMAkGA1UEBhMCVVMxCzAJBgNVBAgMAk5ZMRswGQYDVQQKDBJRWiBJbmR1c3Ry",
    "aWVzLCBMTEMxGzAZBgNVBAsMElFaIEluZHVzdHJpZXMsIExMQzEZMBcGA1UEAwwQ",
    "cXppbmR1c3RyaWVzLmNvbTEnMCUGCSqGSIb3DQEJARYYc3VwcG9ydEBxemluZHVz",
    "dHJpZXMuY29tMB4XDTI1MTEyNDEyNDQzMFoXDTI2MTIwNjIwNTUyNlowgcgxCzAJ",
    "BgNVBAYMAkJSMQ8wDQYDVQQIDAZHb2nDoXMxETAPBgNVBAcMCEdvacOibmlhMQ4w",
    "DAYDVQQKDAVBY2NvbjEOMAwGA1UECwwFQWNjb24xEzARBgNVBAMMCiouYWNjb24u",
    "YWkxIjAgBgkqhkiG9w0BCQEME2xpbmNvbkBhY2Nvbi5jb20uYnIxPDA6BgNVBA0M",
    "M3JlbmV3YWwtb2YtNWU5MDJjNjBmY2NjYjMwMmYwMjQwZTNjN2M2NGFkYTM0NjQw",
    "ZDUyMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAKY01uUGsvPwlpJQ",
    "8IcuuutAj3DR52LRzXMHzoYybfeZAFJIelL4y0qa9Lix5M0AEUWVHtU5ZcjEe8/z",
    "W5bzvUATk/5Znp/7vKPdVTvskFbwSacsjKNYxWkV9+5sNLYkca9SS7FtkRNpYySB",
    "idfNlcuFsbLK7ejhRRcvYeA0UHdcT8NOncbq13WNJkWDglKSaF3pVVB0CassgMW+",
    "0CTYPlCrRaq+qTLJ1BVU7CxVWv55jkVCWsDAX5mVJNHgfPxFEX7mjehb2XWWf66A",
    "h3DJ+r0aa65Z49FJvsxkOMdllf/b92rULvHq8Ax0z4QjkLHtEZ1tXSrXBcsyp/al",
    "H7kI/akCAwEAAaMjMCEwHwYDVR0jBBgwFoAUkKZQt4TUuepf8gWEE3hF6Kl1VFww",
    "DQYJKoZIhvcNAQENBQADggIBADkgUIfgDCzh7zt6yIajhr38bwH+9pQDFQl6NueG",
    "GR+4UHWrvqNIdc5bmCRAJ7Xk/qC7wawdqQdZ4Un5mfFrfWZaHvXaUSj/CNIeo7dA",
    "7CSkegLxFd7bHrKxJkEOdZuARmSwzZbJ2GikG5nBF+YpPMo50umjh+vXzEDAWzwM",
    "5EjHPsfpbIJjsMf9jGE9DTl4EtE97rzv6pjggwpRTTtU4K+WXGqkzddkQt4SLPq+",
    "WfeWludk1o8dl3GEKFX+Lj3XWPgMZr/g7utE3SE/5fBJHXNkdSojmgWrb3nXkmEV",
    "T5vLuQ8WORX35vuPvZ3PsHFHMHJqiZRu5Ic0eaH1mMSnUavzuD3s+uQ45I5bFzri",
    "sCuB1nCGobxPmNeao1GFHMMpdZjpMr9niOMhpNnRwgdX9P2abBoght3mpNLe29fR",
    "hdNqFPAxKbi6nzaWbO2RqdrqDcgPFi3biz9jnQXXpXHsrjs1R4TZNSgdtXcCeThj",
    "nwZaIQAFJ1G42fUXScI8BEvgXyL49KksEZ7KgsnuI01x2eH6d93LGTNISmdD0Ei/",
    "1kZ+KcfiAlj4lI2VIVbQfMFg4zXc6Mho1ckot23HGApVgu+EWJt95yX+kXoGTpVk",
    "NUuviw36BZzbU9mKx97uG8YGi4gOQlbKUtsyiCo3fQmD4E1lsulfI/cJJnltIidb",
    "YRAJ",
]

pem = "-----BEGIN CERTIFICATE-----\n"
pem += "\n".join(cert_lines)
pem += "\n-----END CERTIFICATE-----\n"

with open('/tmp/accon.pem', 'w') as f:
    f.write(pem)
print("OK: /tmp/accon.pem criado")
PYEOF

echo "Limpando blocked.dat..."
printf '#%s\n' "$(date)" > /home/pi/.qz/blocked.dat

echo "Registrando certificado no QZ Tray e iniciando..."
/opt/qz-tray/qz-tray --allow /tmp/accon.pem &

echo ""
echo "QZ Tray iniciando... aguarde e recarregue o portal do Accon."
