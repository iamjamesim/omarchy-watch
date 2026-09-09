import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.iamjamesim.omarchy-watch"
  ipcTarget: "omarchy.watch"

  property var state: ({
    schema: 1,
    status: "stopped",
    name: "",
    paired: false,
    connected: false,
    lastSynced: 0,
    brightness: 50,
    message: "Watch service is not running"
  })
  property string actionError: ""

  readonly property string ctlPath: String(setting("ctlPath", "omarchy-watchctl"))
  readonly property string statePath: (Quickshell.env("XDG_STATE_HOME")
    || Quickshell.env("HOME") + "/.local/state") + "/omarchy-watch/status.json"
  readonly property string status: String(state.status || "stopped")
  readonly property bool found: ["found", "pairing", "paired", "syncing", "ready", "error", "disconnected", "bluetooth-off"].indexOf(status) >= 0
  readonly property bool owned: Boolean(state.paired || state.watchOwned)
  readonly property bool needsPairing: !owned && ["found", "pairing", "error"].indexOf(status) >= 0
  readonly property bool ready: status === "ready"
  readonly property bool pending: String(state.desiredRevision || "") !== ""
    && String(state.desiredRevision || "") !== String(state.syncedRevision || "")
  readonly property bool recovering: owned && !ready && status !== "syncing" && status !== "paired"
  readonly property bool busy: status === "pairing" || status === "syncing" || command.running
  readonly property bool brightnessAvailable: Number(state.protocol || 0) >= 3
    && (Number(state.capabilities || 0) & 32) !== 0
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.45)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  visible: found && (status !== "bluetooth-off" || owned)
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function applyState(raw) {
    try {
      var previousStatus = status
      var parsed = JSON.parse(raw)
      if (Number(parsed.schema) !== 1) throw new Error("Unsupported status schema")
      state = parsed
      actionError = ""
      if ((parsed.status === "found" || parsed.status === "error")
          && previousStatus === "pairing") {
        codeField.text = ""
        if (opened) Qt.callLater(function() { codeField.forceActiveFocus() })
      }
    } catch (error) {
      state = {
        schema: 1,
        status: "error",
        name: "Omarchy Watch",
        message: "Could not read watch status"
      }
    }
  }

  function run(arguments) {
    if (command.running) return
    actionError = ""
    command.command = [ctlPath].concat(arguments)
    command.running = true
  }

  function submitCode() {
    var digits = codeField.text.replace(/\s/g, "")
    if (!/^\d{6}$/.test(digits)) {
      actionError = "Enter all six digits shown on the watch"
      return
    }
    run(["pair", digits])
  }

  function relativeSync(epoch) {
    var seconds = Math.max(0, Math.floor(Date.now() / 1000) - Number(epoch || 0))
    if (seconds < 10) return "JUST NOW"
    if (seconds < 60) return seconds + " SECONDS AGO"
    var minutes = Math.floor(seconds / 60)
    if (minutes < 60) return minutes + " MINUTES AGO"
    var hours = Math.floor(minutes / 60)
    return hours + " HOURS AGO"
  }

  onOpenedChanged: if (opened) {
    stateFile.reload()
    if (status === "found") Qt.callLater(function() { codeField.forceActiveFocus() })
  }

  FileView {
    id: stateFile
    path: root.statePath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.applyState(text())
  }

  Process {
    id: command
    running: false
    command: []
    stderr: StdioCollector { id: commandError; waitForEnd: true }
    onExited: function(exitCode) {
      if (exitCode !== 0) actionError = String(commandError.text || "Watch command failed").trim()
      stateFile.reload()
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰖉"
    active: root.status === "found" || root.status === "pairing" || root.status === "error"
    foreground: root.ready ? root.barForeground : root.dim
    onPressed: root.toggle()
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: codeField.visible ? codeField : recoveryButton.visible ? recoveryButton : syncButton
    contentWidth: panel.fittedContentWidth(Style.space(320))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    ColumnLayout {
      id: content
      width: parent.width
      spacing: Style.space(14)

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(12)

        Text {
          text: "󰖉"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.display
        }

        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.space(2)

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: String(root.state.name || "OMARCHY WATCH")
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: root.status === "found" ? "READY TO PAIR"
              : root.status === "pairing" ? "PAIRING"
              : root.status === "syncing" ? "SYNCHRONIZING"
              : root.status === "ready" && root.pending ? "SYNC PENDING"
              : root.status === "ready" ? "UP TO DATE"
              : root.status === "bluetooth-off" ? "BLUETOOTH OFF"
              : root.status === "disconnected" ? "DISCONNECTED"
              : root.owned && root.status === "error" ? "DISCONNECTED"
              : root.status.toUpperCase()
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 1.2
          }
        }
      }

      PanelSeparator { Layout.fillWidth: true }

      ColumnLayout {
        visible: root.needsPairing && root.status !== "pairing"
        Layout.fillWidth: true
        spacing: Style.space(8)

        PanelSectionHeader {
          text: "ENTER CODE SHOWN ON WATCH"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          TextField {
            id: codeField
            Layout.fillWidth: true
            placeholderText: "000 000"
            foreground: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            horizontalAlignment: TextInput.AlignHCenter
            maximumLength: 6
            inputMethodHints: Qt.ImhDigitsOnly
            validator: RegularExpressionValidator { regularExpression: /[0-9]{0,6}/ }
            onAccepted: root.submitCode()
          }

          Button {
            text: "PAIR"
            bordered: true
            focusable: true
            enabled: codeField.text.length === 6 && !root.busy
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.submitCode()
          }
        }
      }

      ColumnLayout {
        visible: root.status === "pairing" || root.status === "syncing" || root.status === "paired"
        Layout.fillWidth: true
        spacing: Style.space(6)

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(root.state.message || "Finishing setup")
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          Layout.fillWidth: true
          text: "•••"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }
      }

      ColumnLayout {
        visible: root.recovering
        Layout.fillWidth: true
        spacing: Style.space(10)

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(root.state.message || "Watch is temporarily unavailable")
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.WordWrap
        }

        Button {
          id: recoveryButton
          visible: root.status !== "bluetooth-off"
          Layout.fillWidth: true
          text: root.busy ? "RECONNECTING" : "RECONNECT + SYNC"
          bordered: true
          focusable: true
          enabled: !root.busy
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.run(["sync"])
        }

      }

      ColumnLayout {
        visible: root.ready
        Layout.fillWidth: true
        spacing: Style.space(8)

        PanelSectionHeader {
          text: "STATUS"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        RowLayout {
          Layout.fillWidth: true

          Text {
            text: "TIME + WEATHER + THEME"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          Item { Layout.fillWidth: true }

          Text {
            text: root.pending ? "WAITING TO SYNC" : root.relativeSync(root.state.lastSynced)
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Button {
          id: syncButton
          Layout.fillWidth: true
          text: root.busy ? "SYNCING" : "SYNC NOW"
          bordered: true
          focusable: true
          enabled: !root.busy
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.run(["sync"])
        }

        PanelSeparator {
          visible: root.brightnessAvailable
          Layout.fillWidth: true
        }

        PanelSectionHeader {
          visible: root.brightnessAvailable
          text: "DISPLAY"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        RowLayout {
          visible: root.brightnessAvailable
          Layout.fillWidth: true

          Text {
            text: "BRIGHTNESS"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          Item { Layout.fillWidth: true }

          Text {
            text: Math.round(brightnessSlider.liveValue) + "%"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        PanelSlider {
          id: brightnessSlider
          visible: root.brightnessAvailable
          Layout.fillWidth: true
          bar: root.bar
          minimum: 20
          maximum: 100
          step: 5
          integer: true
          value: Number(root.state.brightness || 50)
          enabled: !root.busy
          onReleased: function(value) {
            root.run(["brightness", String(Math.round(value))])
          }
        }

        Text {
          Layout.alignment: Qt.AlignHCenter
          textFormat: Text.PlainText
          text: "WEATHER DATA BY OPEN-METEO.COM"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: Qt.openUrlExternally("https://open-meteo.com/")
          }
        }
      }

      Text {
        visible: root.actionError !== "" || (!root.owned && root.status === "error")
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: root.actionError !== "" ? root.actionError : String(root.state.message || "Pairing failed")
        color: bar ? bar.urgent : Color.urgent
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }
    }
  }
}
