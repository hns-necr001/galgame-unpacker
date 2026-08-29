// GUI 控件桩:仅用于让 GARbro 格式源码在无 GUI 环境下编译。
// 解包流程不会调用这些控件(GUI 专属),这里只提供最小可编译实现。
using System.Windows.Controls;

namespace GUI
{
    public class StubWidget
    {
        public TextBox Password { get; } = new TextBox();
        public StubWidget(params object[] _) { }
    }

    public class WidgetXP3 : StubWidget { public WidgetXP3(params object[] _) : base(_) { } }
    public class WidgetZIP : StubWidget { public WidgetZIP(params object[] _) : base(_) { } }
    public class WidgetAZ : StubWidget { public WidgetAZ(params object[] _) : base(_) { } }
    public class WidgetYPF : StubWidget { public WidgetYPF(params object[] _) : base(_) { } }
    public class WidgetPCK : StubWidget { public WidgetPCK(params object[] _) : base(_) { } }
    public class WidgetTactics : StubWidget { public WidgetTactics(params object[] _) : base(_) { } }
    public class WidgetKCAP : StubWidget { public WidgetKCAP(params object[] _) : base(_) { } }
    public class WidgetWARC : StubWidget { public WidgetWARC(params object[] _) : base(_) { } }
    public class WidgetQLIE : StubWidget { public WidgetQLIE(params object[] _) : base(_) { } }
    public class WidgetAGS : StubWidget { public WidgetAGS(params object[] _) : base(_) { } }
    public class WidgetBELL : StubWidget { public WidgetBELL(params object[] _) : base(_) { } }
    public class WidgetDPK : StubWidget
    {
        public TextBox Key1 { get; } = new TextBox();
        public TextBox Key2 { get; } = new TextBox();
        public WidgetDPK(params object[] _) : base(_) { }
    }
    public class WidgetMCG : StubWidget
    {
        public byte GetKey() => 0;
        public WidgetMCG(params object[] _) : base(_) { }
    }
    public class WidgetINT : StubWidget
    {
        public GameRes.Formats.CatSystem.IntEncryptionInfo Info { get; set; }
        public WidgetINT(params object[] _) : base(_) { }
    }
    public class WidgetARC : StubWidget { public WidgetARC(params object[] _) : base(_) { } }
    public class WidgetEAGLS : StubWidget { public WidgetEAGLS(params object[] _) : base(_) { } }    public class WidgetGAL : StubWidget { public WidgetGAL(params object[] _) : base(_) { } }
    public class WidgetGYU : StubWidget { public WidgetGYU(params object[] _) : base(_) { } }
    public class WidgetISF : StubWidget { public WidgetISF(params object[] _) : base(_) { } }
    public class WidgetLEAF : StubWidget { public WidgetLEAF(params object[] _) : base(_) { } }
    public class WidgetLPK : StubWidget { public WidgetLPK(params object[] _) : base(_) { } }
    public class WidgetMBL : StubWidget { public WidgetMBL(params object[] _) : base(_) { } }
    public class WidgetMGPK : StubWidget { public WidgetMGPK(params object[] _) : base(_) { } }
    public class WidgetMSD : StubWidget { public WidgetMSD(params object[] _) : base(_) { } }
    public class WidgetNCARC : StubWidget { public WidgetNCARC(params object[] _) : base(_) { } }
    public class WidgetNOA : StubWidget { public WidgetNOA(params object[] _) : base(_) { } }
    public class WidgetNPA : StubWidget { public WidgetNPA(params object[] _) : base(_) { } }
    public class WidgetNPK : StubWidget { public WidgetNPK(params object[] _) : base(_) { } }
    public class WidgetNSA : StubWidget { public WidgetNSA(params object[] _) : base(_) { } }
    public class WidgetPAZ : StubWidget { public WidgetPAZ(params object[] _) : base(_) { } }
    public class WidgetRCT : StubWidget { public WidgetRCT(params object[] _) : base(_) { } }
    public class WidgetSCR : StubWidget { public WidgetSCR(params object[] _) : base(_) { } }
    public class WidgetSJDAT : StubWidget { public WidgetSJDAT(params object[] _) : base(_) { } }

    public class CreateAMIWidget : StubWidget { public CreateAMIWidget(params object[] _) : base(_) { } }
    public class CreateARCWidget : StubWidget { public CreateARCWidget(params object[] _) : base(_) { } }
    public class CreateINTWidget : StubWidget { public CreateINTWidget(params object[] _) : base(_) { } }
    public class CreateNPAWidget : StubWidget { public CreateNPAWidget(params object[] _) : base(_) { } }
    public class CreateONSWidget : StubWidget { public CreateONSWidget(params object[] _) : base(_) { } }
    public class CreatePDWidget : StubWidget { public CreatePDWidget(params object[] _) : base(_) { } }
    public class CreateRPAWidget : StubWidget { public CreateRPAWidget(params object[] _) : base(_) { } }
    public class CreateSGWidget : StubWidget { public CreateSGWidget(params object[] _) : base(_) { } }
    public class CreateXP3Widget : StubWidget { public CreateXP3Widget(params object[] _) : base(_) { } }
    public class CreateYPFWidget : StubWidget { public CreateYPFWidget(params object[] _) : base(_) { } }
}

// WidgetARC 属于 GameRes.Formats.Rpm(官方是 XAML 控件,此处提供最小桩)
namespace GameRes.Formats.Rpm
{
    public class WidgetARC
    {
        public WidgetARC(params object[] _) { }
    }
}
