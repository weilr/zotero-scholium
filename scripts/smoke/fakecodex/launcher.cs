// fakecodex.exe: the executable the plugin's codexPath names in a throwaway Zotero (scripts/smoke/live.py --fake-codex).
// It starts fake_codex.py beside it with the Python that python.txt beside it names (else `python` on PATH) and pipes
// stdin, stdout and stderr through, so that the plugin's Subprocess talks to the fake as to codex.exe. No model is called.
//
// Build (the .NET Framework compiler ships with Windows):
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /out:fakecodex.exe launcher.cs
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;

class FakeCodexLauncher {
    static void Pump(Stream from, Stream to, bool closeTo) {
        var buf = new byte[65536];
        try {
            int n;
            while ((n = from.Read(buf, 0, buf.Length)) > 0) { to.Write(buf, 0, n); to.Flush(); }
        } catch (Exception) {}
        if (closeTo) { try { to.Close(); } catch (Exception) {} }
    }

    static int Main(string[] args) {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string named = Path.Combine(dir, "python.txt");
        string py = File.Exists(named) ? File.ReadAllText(named).Trim() : "python";
        string script = Path.Combine(dir, "fake_codex.py");
        var psi = new ProcessStartInfo(py);
        psi.Arguments = "-u -X utf8 \"" + script + "\" " + string.Join(" ", args.Select(a => "\"" + a.Replace("\"", "\\\"") + "\""));
        psi.UseShellExecute = false;
        psi.RedirectStandardInput = true;
        psi.RedirectStandardOutput = true;
        psi.RedirectStandardError = true;
        var p = Process.Start(psi);
        var tin = new Thread(() => Pump(Console.OpenStandardInput(), p.StandardInput.BaseStream, true));
        tin.IsBackground = true;
        tin.Start();
        var tout = new Thread(() => Pump(p.StandardOutput.BaseStream, Console.OpenStandardOutput(), false));
        var terr = new Thread(() => Pump(p.StandardError.BaseStream, Console.OpenStandardError(), false));
        tout.Start();
        terr.Start();
        p.WaitForExit();
        tout.Join();
        terr.Join();
        return p.ExitCode;
    }
}
