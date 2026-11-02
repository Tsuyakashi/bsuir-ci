# Dockerfile
FROM python:3.8-slim

# Установка рабочего каталога в контейнере
WORKDIR /app

# Копирование файлов в контейнер
COPY . /app

# Установка зависимостей
RUN pip install flask

# Определение порта, на котором будет работать приложение
EXPOSE 80

# Запуск приложения
CMD ["python", "app.py"]
