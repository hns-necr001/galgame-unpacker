// GARbro 核心命令行解包工具(供 Python 前端 subprocess 调用)
// 用法:
//   garbro_cli formats                   列出支持的档案格式
//   garbro_cli extract <路径> <输出目录>  解包文件或目录下所有档案
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using GameRes;

namespace GarbroCli
{
    class Program
    {
        static int Main(string[] args)
        {
            Console.OutputEncoding = Encoding.UTF8;
            Console.InputEncoding = Encoding.UTF8;
            // Formats.dat(BinaryFormatter)引用了旧程序集名 GameRes,重定向到当前程序集
            AppDomain.CurrentDomain.AssemblyResolve += (s, e) =>
            {
                var name = new AssemblyName(e.Name);
                if (name.Name == "GameRes" || name.Name == "ArcFormats")
                    return typeof(Program).Assembly;
                return null;
            };
            var listener = new TextWriterTraceListener(Console.Error);
            Trace.Listeners.Add(listener);
            try
            {
                if (args.Length == 0)
                {
                    Usage();
                    return 1;
                }
                switch (args[0])
                {
                    case "formats":
                        return ListFormats();
                    case "extract":
                        if (args.Length < 3) { Usage(); return 1; }
                        return Extract(args[1], args[2]);
                    default:
                        Console.Error.WriteLine("未知命令: " + args[0]);
                        Usage();
                        return 1;
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("错误: " + ex);
                return 1;
            }
        }

        static int ListFormats()
        {
            DeserializeGameData();
            foreach (var impl in FormatCatalog.Instance.ArcFormats.OrderBy(f => f.Tag))
                Console.WriteLine("{0,-6} {1}", impl.Tag, impl.Description);
            return 0;
        }

        static int Extract(string input, string outdir)
        {
            DeserializeGameData();
            if (!Directory.Exists(input) && !File.Exists(input))
            {
                Console.Error.WriteLine("路径不存在: " + input);
                return 1;
            }
            Directory.CreateDirectory(outdir);
            var filePaths = new System.Collections.Generic.List<string>();
            if (Directory.Exists(input))
                filePaths.AddRange(Directory.GetFiles(input, "*", SearchOption.AllDirectories));
            else if (File.Exists(input))
                filePaths.Add(input);
            int ok = 0, fail = 0;
            foreach (var filePath in filePaths)
            {
                ArcFile arc;
                try
                {
                    VFS.ChDir(filePath);
                    arc = ((ArchiveFileSystem)VFS.Top).Source;
                }
                catch (Exception ex)
                {
                    if (!(ex is GameRes.UnknownFormatException) && !string.IsNullOrEmpty(ex.Message) && ex.Message.Contains("specified file"))
                    {
                        // 非档案文件静默跳过
                    }
                    else
                        Console.Error.WriteLine("[跳过] " + Path.GetFileName(filePath) + " : " + ex.Message);
                    ++fail;
                    continue;
                }
                // 复位 VFS 栈(确保下一个文件从物理文件系统打开)
                while (VFS.IsVirtual)
                {
                    try { VFS.ChDir(".."); } catch { break; }
                }
                string arcName = Path.GetFileName(filePath);
                var old = Directory.GetCurrentDirectory();
                try
                {
                    Directory.SetCurrentDirectory(outdir);
                    arc.ExtractFiles((i, entry, msg) =>
                    {
                        if (entry != null)
                            Console.WriteLine("[" + arcName + "] " + entry.Name);
                        else if (!string.IsNullOrEmpty(msg))
                            Console.Error.WriteLine(msg);
                        return ArchiveOperation.Continue;
                    });
                }
                finally
                {
                    Directory.SetCurrentDirectory(old);
                }
                ++ok;
                Console.WriteLine("[完成] " + arcName);
            }
            Console.WriteLine("== 解包完成: " + ok + " 个档案, " + fail + " 个跳过 ==");
            return fail > 0 && ok == 0 ? 1 : 0;
        }

        static void DeserializeGameData()
        {
            string schemeFile = Path.Combine(FormatCatalog.Instance.DataDirectory, "Formats.dat");
            try
            {
                using (var file = File.OpenRead(schemeFile))
                    FormatCatalog.Instance.DeserializeScheme(file);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("Formats.dat 加载失败: " + ex.Message);
            }
        }

        static int Usage()
        {
            Console.WriteLine("用法: garbro_cli formats");
            Console.WriteLine("      garbro_cli extract <路径> <输出目录>");
            return 1;
        }
    }
}
