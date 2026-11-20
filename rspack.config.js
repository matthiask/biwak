module.exports = (env, argv) => {
  const {
    base,
    devServer,
    assetRule,
    postcssRule,
    sassRule,
    swcWithPreactRule,
  } = require("./rspack.library.js")(argv.mode === "production")

  // No core-js: all browsers we support have what the scripts use
  const swcRule = swcWithPreactRule()
  swcRule.options.env = {}

  // The live editing of docs (specs/collaboration.md) needs its websockets
  // passed on to Django too (the dev server's own are at /ws)
  const server = devServer({ backendPort: env.backend })
  if (env.backend) {
    server.proxy.unshift({
      context: ["/ws/docs/"],
      target: `ws://127.0.0.1:${env.backend}`,
      ws: true,
    })
  }

  return {
    ...base,
    // rspack serve compiles dynamic imports lazily, but its requests to
    // /_rspack/lazy/trigger end up in Django (the proxy takes everything)
    lazyCompilation: false,
    devServer: server,
    module: {
      rules: [
        assetRule(),
        postcssRule({ plugins: ["autoprefixer"] }),
        sassRule(),
        swcRule,
      ],
    },
  }
}
