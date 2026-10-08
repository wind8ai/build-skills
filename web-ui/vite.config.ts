import { defineConfig } from "vite";
export default defineConfig({
  build: { outDir: "../src/build_skills/web/static", emptyOutDir: true },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8321",
        changeOrigin: true,
        configure(proxy) {
          proxy.on("proxyReq", (req: any) =>
            req.setHeader("origin", "http://127.0.0.1:8321"),
          );
        },
      },
    },
  },
});
