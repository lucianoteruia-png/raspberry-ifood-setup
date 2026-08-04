#!/bin/bash
# setup_zebra.sh
# Configura a Raspberry Pi como servidor de impressão Zebra (Kdabra)

GITHUB_RAW="https://raw.githubusercontent.com/lucianoteruia-png/raspberry-ifood-setup/main"
INSTALL_PATH="/opt/auto_setup_impressora.py"
CREDS_PATH="/opt/firebase_creds.json"

echo ""
echo "Instalando dependências Python..."
pip3 install google-auth requests --break-system-packages -q \
    || pip3 install google-auth requests -q

echo "Baixando script..."
curl -fsSL "$GITHUB_RAW/auto_setup_impressora.py" -o "$INSTALL_PATH" \
    || { echo "ERRO: Falha ao baixar. Verifique a conexão."; exit 1; }

echo "Configurando credenciais Firebase..."
cat > "$CREDS_PATH" << 'JSONEOF'
{
  "type": "service_account",
  "project_id": "impressoras-etiquetas",
  "private_key_id": "07a59b913d1e3bf9c9bb47ed6e8c736ed0220429",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCqQtajegyVrdBl\ns4QxM91to9aX2hkl7er4CZGA/Csv9eKEvgu8Mm5F427fBvtcQm6cL/wGvwrSeh6L\nLh/aWWepny1nreHnsafC1eMk/5Lk4sNBHqyvqxnaIiC6RrsyNOzOxNyd5Gd9IMpU\nf9xdtviue8203l2PH+R1Ptflesz+M9FITSMHCw+Mc5lh6yhbxrs/NdDZhr1X4nmL\nI+x/P0hxgwDU8/PBINHrIUUcuCVv44U4a7wyw6NvMy1RoL1j9j67O1wXPiO3p19N\nwpWBXpoVqCavBy6ZOSXUZxoaHRI0gCkZBjb+UP8wMn2UNcZk04O3VZnCLZafSARC\nplRPwVepAgMBAAECggEAPwBVgQ9n+bjj7MYVC8nXzTq7bNxIwva7JAYSX8qvxmLz\na1ARcpWspVLHk2J3f4ebe1LsLKjjfcevZqvuIHNFvwfGGt/GQGBGJfvUPbwOZICe\nZInPt38WJVfMiXEj0quv1sEUq545Rx1rkQHxDoJmmdX4480GjK/t7w6Of/1FPmhe\njcKNSCnaIVBhlLVKKo/vZu61gmNkuhHd6wQANsRxV/rfGWdcUeUsYHbOmzTW6QPG\nnTQ6HKulOcgyiPY/fXSq821oCY82TXLmLwP3Sk7xh2S6JKh3+2Uk8B1MmTBvbt6l\nrGA251c0BEGx5r6c0hKqBosj1KB/ZE1GsbY25bhXywKBgQDZa5CZ9yBQUqOSGwac\nIle9TF38t1yYJEyM12GT3KzVgEk7Jvnh0JuGG0tfhlYJmPSxHv8xYGDfgGu84rpn\n1Wq27/8IzCcjzoQHjpuKKFuzhBpki4PvWvFwdXQuRIp3aFgtVYooUeLM6VI2go7W\nqk6hjyUAvvBlWS+xz34ACvQbMwKBgQDIeQuSQ+E+N/RdbWzgIPvSNY8S8C+cw752\nLjW/TfiDX9AotQIESYyCNT06bKoiaEG83rc97JhG+093eQKGmvlAD8O6fRPS1+cI\nPHTWTGjiHuhajJXgtMUgZSNF4Dv/fL6DXzhl2ouaXTzd6p0z4nL6hOfas+y5uUfB\n9p+olCxhswKBgEqZA3YwOmAU2paIu03a4qvKhfztlNGGstUoGQy4jHx8laO8DcSS\n5Kmwt73Aw8hrOJmE/x4b6WEGGPEoAbkampDF64VDNrKsatSE840Fp+ECFGQnEk+P\nroNdaU1uquupW4fCb7LB1cVk0JZvWT8CFBSOnq2Q1b6QSTMC9EJjf7nNAoGAS0iB\nmuzY0kerAcbNAyH/z0IDt6XxC1rK1JCn6G58a8F4Z0EKP9fq5x7dHmqePYuPXED6\n6UtHKCjJ/+C2nRvnjDIfW5IK9rvTa9lgOvW40Wmv8gknY5ofCPpSE7SQc3JCDQ2e\nHUnD8TUgXWn0nP5mFUQB2bSFqn00wFdAP8tdG1cCgYAWn7r0KwkWzLVRKq0AooPa\n9NGjBJcjzS3P2TQyFcgQwWE+EINxR2S5UpuXveWEEDS80pxBh0ewTxmTZ4FJhctw\nZEwSL7oThlVoJOkaJsaIhzpr3T6NZEtZiiIt/ovP9Yo/TZMmL3cGiDEqrSxHiXkW\no8OK5y7POKP3+4pem/eZOQ==\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@impressoras-etiquetas.iam.gserviceaccount.com",
  "client_id": "117471603464454861042",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40impressoras-etiquetas.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}
JSONEOF

chmod +x "$INSTALL_PATH"
echo "Iniciando setup..."
sudo python3 "$INSTALL_PATH"
