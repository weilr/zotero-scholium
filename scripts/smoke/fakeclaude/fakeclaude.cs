// A stand-in for Claude Code's `claude` program in a throwaway Zotero: no model is called, nothing leaves the machine.
//
// Its folder is SCHOLIUM_FAKE_DIR when that is set (the smoke runner sets it to the run's own fake folder), else the
// folder of the program. In it:
// - models.json: the answer to the plugin's model-list call (the call with --input-format).
// - scripts\<name>.jsonl: a recorded stream-json run. <name> is the first line of next.txt (default "answer"). Lines:
//   a JSON event (printed as is; {{SESSION}} becomes the session id: the --resume argument, else a new one),
//   "#delay <ms>", "#stream <ms per piece> <text>" (the text as stream_event text deltas, three characters a piece),
//   "#wait" (until killed), "#exit <code>", "#next <name>" (writes next.txt for the following call), "//" comments.
// - calls\<n>.txt: each call, numbered: its script name, a line "ENV SCHOLIUM_ZOTERO_PORT=<value>" (the port the
//   plugin gives the skill's script; empty when unset), its arguments, a line "---", and its standard input.
//
// Build (no Visual Studio needed; the .NET Framework compiler ships with Windows):
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /out:fakeclaude.exe fakeclaude.cs
using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;

class FakeClaude {
    static int Main(string[] args) {
        string env = Environment.GetEnvironmentVariable("SCHOLIUM_FAKE_DIR");
        string dir = !string.IsNullOrEmpty(env) && Directory.Exists(env) ? env : AppDomain.CurrentDomain.BaseDirectory;
        var utf8 = new UTF8Encoding(false);
        var stdout = new StreamWriter(Console.OpenStandardOutput(), utf8);
        stdout.AutoFlush = true;
        var stdin = new StreamReader(Console.OpenStandardInput(), utf8);
        Directory.CreateDirectory(Path.Combine(dir, "calls"));
        int n = Directory.GetFiles(Path.Combine(dir, "calls")).Length + 1;
        string callPath = Path.Combine(dir, "calls", n.ToString("D3") + ".txt");
        string envLine = "ENV SCHOLIUM_ZOTERO_PORT=" + (Environment.GetEnvironmentVariable("SCHOLIUM_ZOTERO_PORT") ?? "") + "\n";
        if (args.Contains("--input-format")) {
            string first = stdin.ReadLine() ?? "";
            File.WriteAllText(callPath, "MODELS\n" + envLine + string.Join("\n", args) + "\n---\n" + first, utf8);
            stdout.WriteLine(File.ReadAllText(Path.Combine(dir, "models.json"), utf8).Trim());
            return 0;
        }
        string prompt = stdin.ReadToEnd();
        string name = "answer";
        string nextPath = Path.Combine(dir, "next.txt");
        if (File.Exists(nextPath)) {
            string t = File.ReadAllText(nextPath, utf8).Trim();
            if (t.Length > 0) name = t.Split('\n')[0].Trim();
        }
        File.WriteAllText(callPath, name + "\n" + envLine + string.Join("\n", args) + "\n---\n" + prompt, utf8);
        string session = Guid.NewGuid().ToString();
        int r = Array.IndexOf(args, "--resume");
        if (r >= 0 && r + 1 < args.Length) session = args[r + 1];
        string script = Path.Combine(dir, "scripts", name + ".jsonl");
        foreach (string raw in File.ReadAllLines(script, utf8)) {
            string line = raw.TrimEnd();
            if (line.Length == 0 || line.StartsWith("//")) continue;
            if (line.StartsWith("#delay ")) { Thread.Sleep(int.Parse(line.Substring(7).Trim())); continue; }
            if (line == "#wait") { Thread.Sleep(Timeout.Infinite); }
            if (line.StartsWith("#exit ")) return int.Parse(line.Substring(6).Trim());
            if (line.StartsWith("#next ")) { File.WriteAllText(nextPath, line.Substring(6).Trim(), utf8); continue; }
            if (line.StartsWith("#stream ")) {
                string rest = line.Substring(8);
                int sp = rest.IndexOf(' ');
                int ms = int.Parse(rest.Substring(0, sp));
                string text = rest.Substring(sp + 1).Replace("\\n", "\n");
                stdout.WriteLine("{\"type\":\"stream_event\",\"session_id\":\"" + session + "\",\"event\":{\"type\":\"message_start\"}}");
                for (int i = 0; i < text.Length; i += 3) {
                    string piece = text.Substring(i, Math.Min(3, text.Length - i));
                    stdout.WriteLine("{\"type\":\"stream_event\",\"session_id\":\"" + session + "\",\"event\":{\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":" + Json(piece) + "}}}");
                    Thread.Sleep(ms);
                }
                continue;
            }
            stdout.WriteLine(line.Replace("{{SESSION}}", session));
        }
        return 0;
    }

    static string Json(string s) {
        var b = new StringBuilder("\"");
        foreach (char c in s) {
            if (c == '"') b.Append("\\\"");
            else if (c == '\\') b.Append("\\\\");
            else if (c == '\n') b.Append("\\n");
            else if (c == '\r') b.Append("\\r");
            else if (c == '\t') b.Append("\\t");
            else if (c < 0x20) b.Append("\\u" + ((int)c).ToString("x4"));
            else b.Append(c);
        }
        return b.Append('"').ToString();
    }
}
