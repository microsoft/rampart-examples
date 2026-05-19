// HTTP bridge: forwards requests from inside the Docker Sandbox
// through Docker's HTTP proxy to the auth-proxy on the host.
//
// Environment variables:
//   AUTH_PROXY_PORT  - Host port where auth-proxy listens (default: 12435)
//   BRIDGE_PORT      - Local port to listen on (default: 54321)
//   HTTP_PROXY       - Docker's HTTP proxy URL (auto-set by Docker)

const http = require("http");
const { URL } = require("url");

const PROXY = new URL(process.env.HTTP_PROXY || "http://host.docker.internal:3128");
const AUTH_PROXY_PORT = process.env.AUTH_PROXY_PORT || "12435";
const BRIDGE_PORT = parseInt(process.env.BRIDGE_PORT || "54321", 10);
const TARGET = "localhost:" + AUTH_PROXY_PORT;

const server = http.createServer((req, res) => {
  const proxyReq = http.request(
    {
      hostname: PROXY.hostname,
      port: PROXY.port,
      path: "http://" + TARGET + req.url,
      method: req.method,
      headers: { ...req.headers, host: TARGET },
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res);
    }
  );

  proxyReq.on("error", (e) => {
    console.error("Bridge error:", e.message);
    if (!res.headersSent) {
      res.writeHead(502);
      res.end("Bridge error: " + e.message);
    }
  });

  req.pipe(proxyReq);
});

server.listen(BRIDGE_PORT, "127.0.0.1", () => {
  console.log("Bridge: 127.0.0.1:" + BRIDGE_PORT + " -> host " + TARGET);
});
