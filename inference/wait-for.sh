#!/usr/bin/env bash
# wait-for-kafka.sh

host="$1"
port="$2"
shift 2
cmd="$@"

until nc -z "$host" "$port"; do
  >&2 echo "⏳ Ожидаем $host:$port..."
  sleep 1
done

>&2 echo "✅ $host:$port доступен — запускаем команду: $cmd"
exec $cmd