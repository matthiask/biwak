module.exports = (env, argv) => {
  const { base, devServer, assetRule, postcssRule, sassRule, swcWithPreactRule } =
    require("./rspack.library.js")(argv.mode === "production")

  // No core-js: all browsers we support have what the scripts use
  const swcRule = swcWithPreactRule()
  swcRule.options.env = {}

  return {
    ...base,
    // rspack serve compiles dynamic imports lazily, but its requests to
    // /_rspack/lazy/trigger end up in Django (the proxy takes everything)
    lazyCompilation: false,
    devServer: devServer({ backendPort: env.backend }),
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
