import datetime
import logging
from flask import Flask, request, render_template
from werkzeug.middleware.proxy_fix import ProxyFix


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)

app = Flask(__name__)

# Behind Tailscale Serve/Funnel: trust exactly one proxy hop for the client IP.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

def get_cpu_load():
    try:
        with open("/proc/loadavg", "r") as f:
            load_1min = f.read().split()[0]
        return load_1min
    except Exception as e:
        app.logger.error(f"Failed to get CPU load: {e}")
        return "N/A"

@app.before_request
def log_request_info():
    if request.path != '/health':
        app.logger.info(f"HTTP {request.method} {request.path} from {request.remote_addr}")

@app.route('/')
def hello_world():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cpu_load = get_cpu_load()
    return render_template('index.html', timestamp=timestamp, cpu_load=cpu_load)

@app.route('/health')
def healthcheck():
    return { "status": "ok" }
