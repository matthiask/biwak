// SPIKE: Hocuspocus syncing docs, asking Django who may connect and
// storing the Markdown through it
import { Server } from "@hocuspocus/server"

const DJANGO = process.env.DJANGO || "http://127.0.0.1:58123"
const TOKEN = process.env.SERVICE_TOKEN || "spike"

const server = new Server({
  port: Number(process.env.PORT || 1234),
  debounce: 2000,
  async onAuthenticate({ documentName, requestHeaders, connectionConfig }) {
    const response = await fetch(`${DJANGO}/collab/hp/${documentName}/auth/`, {
      headers: { cookie: requestHeaders.get("cookie") || "" },
      redirect: "manual",
    })
    if (response.status !== 200) throw new Error(`refused: ${response.status}`)
    const data = await response.json()
    connectionConfig.readOnly = !data.writable
    return { user: data.user }
  },
  async onLoadDocument({ document, documentName }) {
    const response = await fetch(
      `${DJANGO}/collab/hp/${documentName}/content/`,
      {
        headers: { "x-service-token": TOKEN },
      },
    )
    const data = await response.json()
    if (document.getText("content").length === 0) {
      document.getText("content").insert(0, data.content)
    }
  },
  // onStoreDocument doesn't know who changed the document: remember it
  async onChange({ document, context }) {
    if (context?.user) document.lastEditor = context.user
  },
  async onStoreDocument({ document, documentName }) {
    await fetch(`${DJANGO}/collab/hp/${documentName}/content/`, {
      method: "POST",
      headers: { "x-service-token": TOKEN, "content-type": "application/json" },
      body: JSON.stringify({
        content: document.getText("content").toString(),
        user: document.lastEditor,
      }),
    })
  },
})

server.listen()
