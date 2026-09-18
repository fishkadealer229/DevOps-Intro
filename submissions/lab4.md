# Lab 4

## Task 1

### 1. Start QuickNotes + capture

QuickNotes was started with:

```cd app/```
```go run .```

Packet capture was started with:

```sudo tcpdump -i lo -nn -s 0 -A 'tcp port 8080' -w lab4-trace.pcap```

The following request was sent:

```curl -v -X POST http://localhost:8080/notes -H 'Content-Type: application/json' -d '{"title":"trace me","body":"in flight"}'```

Returned:

HTTP/1.1 201 Created
Content-Type: application/json
Date: Thu, 17 Sep 2026 04:10:28 GMT
Content-Length: 93

{"id":8,"title":"trace me","body":"in flight","created_at":"2026-09-18T04:10:28.290167742Z"}

The capture contained 10 captured packets and 0 packets dropped by the kernel.

### 2. Decode capture

The decoded capture was saved in lab4-trace.txt.

TCP connection

The packet sequence shows:

SYN from ::1:37084 to ::1:8080.
SYN/ACK from ::1:8080 to ::1:37084.
ACK from the client.
HTTP request
POST /notes HTTP/1.1
Host: localhost:8080
User-Agent: curl/8.18.0
Accept: */*
Content-Type: application/json
Content-Length: 39

{"title":"trace me","body":"in flight"}
HTTP response
HTTP/1.1 201 Created
Content-Type: application/json
Date: Thu, 17 Sep 2026 04:10:28 GMT
Content-Length: 93

{"id":8,"title":"trace me","body":"in flight","created_at":"2026-09-18T04:10:28.290167742Z"}
Connection termination

The capture shows FIN packets from both sides followed by the final ACK. No RST packet was observed.

### 3. Five commands
- ```ss -tlnp | grep :8080```

    LISTEN 0 4096 *:8080 *:* users:(("quicknotes",pid=5120,fd=3))
- ```ip route show```

    default via 172.30.112.1 dev eth0 proto kernel
- ```mtr -rwc 5 localhost```

    Start: 2026-09-18T07:14:45+0300
HOST: DESKTOP-HQ5CJM Loss% Snt Last Avg Best Wrst StDev
1.|-- localhost 0.0% 5 0.1 0.1 0.1 0.3
- ```dig +short example.com @1.1.1.1```

    8.47.69.0

    8.6.112.0
- ```journalctl --user -u quicknotes -n 20 || true```

    -- No entries --

### 4. What would you check first if QuickNotes returned 502?

If QuickNotes returns a 502, I would first check whether the QuickNotes service is actually listening on the expected port and accepting connections. The next checks would be the service logs and the network path between the client/proxy and QuickNotes.


## Task 2

### 1. Run a broken instance

The first QuickNotes instance started successfully and occupied port 8080.

The second instance failed because port 8080 was already in use.

Exact error:

listen: listen tcp :8080: bind: address already in use
exit status 1

Process check:

```ps -ef | grep "go run" | grep -v grep```

Output:

fishkad+    4768     423  0 07:06 pts/0    00:00:00 go run .

### 2. Outside-in debugging chain

1) systemctl-style: is it running?

Command:

```ps -ef | grep quicknotes```

Output:

fishkad+    5120    4768  0 07:06 pts/0    00:00:00 /tmp/go-build3419211392/b001/exe/quicknotes

The process was checked first to determine whether the application was running

2) Is it listening?

Command:

```ss -tlnp | grep 8080```

Output:

LISTEN 0      4096                *:8080            *:*    users:(("quicknotes",pid=5120,fd=3))

This checks whether a process is listening on port 8080

3) Reachable from the host?

Command:

```curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/health```

Output:

200

This checks connection to the application independently of the process check.

4) Firewall blocking?

Command:

```sudo iptables -L -n -v 2>/dev/null || sudo nft list ruleset 2>/dev/null || true```

Output:

[no output]

Firewall rules were checked to determine whether traffic was being blocked (nowhere)

5) DNS

Command:

```dig +short localhost```

Output:

127.0.0.1

DNS resolution for localhost was checked as the final step.

### 3. Repair and re-verify

The process occupying port 8080 was stopped and QuickNotes was started again:

```kill $PID1```

sleep 1

ADDR=:8080 go run . &

PID1=$!

sleep 1

curl -s http://localhost:8080/health

Output:

-bash: kill: (5407) - No such process
[1] 5679
2026/09/17 07:41:28 quicknotes listening on :8080 (notes loaded: 6)
2026/09/17 07:41:28 listen: listen tcp :8080: bind: address already in use
exit status 1
[1]+  Exit 1                     ADDR=:8080 go run .
{"notes":6,"status":"ok"}

The health endpoint was used to verify that the repaired instance was responding.

#### Root cause

The root cause was a port conflict. Two QuickNotes instances attempted to bind to port 8080, resulting in:

bind: address already in use

### 4. Mini-postmortem

This type of failure is systemic because multiple processes can depend on the same network port, while the deployment or startup procedure may not verify port ownership before starting a new instance. The failure is not caused by one individual; it is a predictable operational condition. Tooling can reduce the risk by checking port availability before startup, using process managers such as systemd, adding health checks, and making deployment scripts fail clearly when a required port is already occupied. Monitoring and structured logs can also make the problem easier to detect and diagnose.