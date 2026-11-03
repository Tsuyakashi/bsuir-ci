bind = "0.0.0.0:80"
workers = 2

accesslog = "-"
access_log_format = (
    '{"time":"%(t)s",'
    '"remote":"%({x-forwarded-for}i)s",'
    '"method":"%(m)s",'
    '"path":"%(U)s",'
    '"query":"%(q)s",'
    '"status":%(s)s,'
    '"bytes":%(B)s,'
    '"duration_ms":%(M)s,'
    '"user_agent":"%(a)s"}'
)
