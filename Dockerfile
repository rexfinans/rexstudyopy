FROM python:3.11-slim

# Botun çalışacağı klasörü ayarla
WORKDIR /app

# Gerekli dosyaları kopyala
COPY . .

# Kütüphaneleri kur
RUN pip install --no-cache-dir -r requirements.txt

# Botun portunu dışarı aç (senin botun 8080 kullanıyor)
EXPOSE 8080

# Botu başlat
CMD ["python", "bot.py"]
