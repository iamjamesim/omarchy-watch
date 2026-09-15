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

  property var watchState: ({
    schema: 1,
    status: "stopped",
    name: "",
    paired: false,
    connected: false,
    lastSynced: 0,
    brightness: 50,
    completionSound: true,
    message: "Watch service is not running"
  })
  property string actionError: ""
  property string autoOpenedCandidate: ""
  property double nowEpoch: Date.now() / 1000

  readonly property string ctlPath: String(setting("ctlPath", "omarchy-watchctl"))
  readonly property string statePath: (Quickshell.env("XDG_STATE_HOME")
    || Quickshell.env("HOME") + "/.local/state") + "/omarchy-watch/status.json"
  readonly property string status: String(watchState.status || "stopped")
  readonly property bool needsPairing: !Boolean(watchState.paired)
    && (status === "found" || status === "pairing"
      || (status === "error" && String(watchState.name || "") !== ""))
  readonly property bool searching: !Boolean(watchState.paired) && !needsPairing
    && ["starting", "stopped", "discovering", "unavailable", "bluetooth-off", "error"].indexOf(status) >= 0
  readonly property bool owned: !needsPairing && Boolean(watchState.paired || watchState.watchOwned)
  readonly property bool ready: status === "ready"
  readonly property bool pending: String(watchState.desiredRevision || "") !== ""
    && String(watchState.desiredRevision || "") !== String(watchState.syncedRevision || "")
  readonly property bool recovering: owned && !ready && status !== "syncing" && status !== "paired"
  readonly property bool busy: status === "pairing" || status === "syncing" || command.running
  readonly property bool brightnessAvailable: Number(watchState.protocol || 0) >= 3
    && (Number(watchState.capabilities || 0) & 32) !== 0
  readonly property bool soundAvailable: (Number(watchState.capabilities || 0) & 128) !== 0
  readonly property string weatherState: String(watchState.weatherStatus || "unknown")
  readonly property bool weatherFailed: Boolean(watchState.weatherFetchFailed)
  readonly property bool weatherRefreshing: Boolean(watchState.weatherRefreshing)
  readonly property string weatherLabel: {
    if (weatherState === "unconfigured") return "SET LOCATION"
    if (weatherRefreshing) return weatherFailed ? "RETRYING" : "UPDATING"
    if (weatherFailed) return "UPDATE FAILED"
    switch (weatherState) {
    case "fresh": return "FRESH"
    case "cached": return "CACHED"
    case "forecast": return "FORECAST ONLY"
    case "unavailable": return "UNAVAILABLE"
    default: return "UNKNOWN"
    }
  }
  readonly property color foreground: root.bar ? root.bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.45)
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : Style.font.family

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function applyState(raw) {
    try {
      var previousStatus = status
      var parsed = JSON.parse(raw)
      if (Number(parsed.schema) !== 1) throw new Error("Unsupported status schema")
      watchState = parsed
      root.actionError = ""
      var candidate = String(parsed.address || "")
      if (parsed.status === "found" && !Boolean(parsed.paired)
          && candidate !== "" && candidate !== autoOpenedCandidate) {
        autoOpenedCandidate = candidate
        Qt.callLater(function() {
          root.open()
          codeField.forceActiveFocus()
        })
      }
      if ((parsed.status === "found" || parsed.status === "error")
          && previousStatus === "pairing") {
        codeField.text = ""
        if (opened) Qt.callLater(function() { codeField.forceActiveFocus() })
      }
    } catch (error) {
      watchState = {
        schema: 1,
        status: "error",
        name: "Omarchy Watch",
        message: "Could not read watch status"
      }
    }
  }

  function run(arguments) {
    if (command.running) return
    root.actionError = ""
    command.command = [ctlPath].concat(arguments)
    command.running = true
  }

  function submitCode() {
    var digits = codeField.text.replace(/\s/g, "")
    if (!/^\d{6}$/.test(digits)) {
      root.actionError = "Enter all six digits shown on the watch"
      return
    }
    run(["pair", digits])
  }

  function relativeSync(epoch) {
    if (!Number(epoch)) return "NEVER"
    var seconds = Math.max(0, Math.floor(nowEpoch) - Number(epoch))
    if (seconds < 10) return "JUST NOW"
    if (seconds < 60) return seconds + " SECOND" + (seconds === 1 ? "" : "S") + " AGO"
    var minutes = Math.floor(seconds / 60)
    if (minutes < 60) return minutes + " MINUTE" + (minutes === 1 ? "" : "S") + " AGO"
    var hours = Math.floor(minutes / 60)
    return hours + " HOUR" + (hours === 1 ? "" : "S") + " AGO"
  }

  function weatherDetail() {
    if (weatherState === "unknown") return "Weather status unavailable."
    if (weatherState === "unconfigured") return "Choose a location in the desktop weather panel."
    var detail
    if (weatherState === "forecast")
      detail = "Current conditions unavailable. Today's high/low only; fetched "
        + relativeSync(watchState.weatherFetched).toLowerCase() + "."
    else if (weatherState === "fresh" || weatherState === "cached")
      detail = (weatherFailed || weatherState === "cached" ? "Using cached conditions from " : "Conditions from ")
        + relativeSync(watchState.weatherUpdated).toLowerCase() + "."
    else
      detail = "No usable weather data."
    if (weatherFailed) detail += " " + (weatherRefreshing ? "Retrying now." : "Retrying automatically.")
    return detail
  }

  onOpenedChanged: if (opened) {
    nowEpoch = Date.now() / 1000
    stateFile.reload()
    if (status === "found") Qt.callLater(function() { codeField.forceActiveFocus() })
  }

  Timer {
    interval: 30000
    running: root.opened
    repeat: true
    onTriggered: root.nowEpoch = Date.now() / 1000
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
      if (exitCode !== 0) root.actionError = String(commandError.text || "Watch command failed").trim()
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
    focusTarget: codeField.visible ? codeField
      : scanButton.visible ? scanButton
      : recoveryButton.visible ? recoveryButton
      : syncButton
    contentWidth: panel.fittedContentWidth(Style.space(320))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    ColumnLayout {
      id: content
      width: parent.width
      spacing: Style.space(14)
      Keys.onEscapePressed: root.close()

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
            text: String(root.watchState.name || "OMARCHY WATCH")
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
              : root.status === "ready" ? "SYNCED"
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
        visible: root.searching
        Layout.fillWidth: true
        spacing: Style.space(10)

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: String(root.watchState.message || "Looking for an Omarchy Watch")
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.WordWrap
        }

        Button {
          id: scanButton
          visible: root.status !== "bluetooth-off"
          Layout.fillWidth: true
          text: root.busy ? "SCANNING" : "SCAN AGAIN"
          bordered: true
          focusable: true
          enabled: !root.busy
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClicked: root.run(["rescan"])
        }
      }

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
          text: String(root.watchState.message || "Finishing setup")
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
          text: String(root.watchState.message || "Watch is temporarily unavailable")
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
            text: "WATCH SYNC"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          Item { Layout.fillWidth: true }

          Text {
            text: root.pending ? "WAITING TO SYNC" : root.relativeSync(root.watchState.lastSynced)
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        RowLayout {
          Layout.fillWidth: true

          Text {
            text: "WEATHER"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          Item { Layout.fillWidth: true }

          Text {
            text: root.weatherLabel
            color: root.weatherFailed ? root.foreground : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Text {
          Layout.fillWidth: true
          textFormat: Text.PlainText
          text: root.weatherDetail()
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
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
          value: Number(root.watchState.brightness || 50)
          enabled: !root.busy
          onReleased: function(value) {
            root.run(["brightness", String(Math.round(value))])
          }
        }

        PanelSeparator {
          visible: root.soundAvailable
          Layout.fillWidth: true
        }

        PanelSectionHeader {
          visible: root.soundAvailable
          text: "CODEX ALERTS"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        RowLayout {
          visible: root.soundAvailable
          Layout.fillWidth: true

          Text {
            text: "SOUND"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          Item { Layout.fillWidth: true }

          ToggleSwitch {
            checked: Boolean(root.watchState.completionSound)
            busy: root.busy
            foreground: root.foreground
            onToggled: root.run([
              "sound", Boolean(root.watchState.completionSound) ? "off" : "on"
            ])
          }
        }

        Text {
          visible: root.soundAvailable
          Layout.fillWidth: true
          text: "Needs input and task completion"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
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
        text: root.actionError !== "" ? root.actionError : String(root.watchState.message || "Pairing failed")
        color: root.bar ? root.bar.urgent : Color.urgent
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }
    }
  }
}
