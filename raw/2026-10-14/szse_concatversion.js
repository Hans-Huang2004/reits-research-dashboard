var szseDomainMap = {
  'mainHttp': [domainMainHttp, backDomainMainHttp],
  'mainHttps': [domainMainHttps, backDomainMainHttps],
  'sso': [domainOwsssoHttps, backDomainOwsssoHttps],
  'bondHttp': [domainBondHttp, backDomainBondHttp],
  'bondHttps': [domainBondHttps, backDomainBondHttps],
  'fundHttp': [domainFundHttp, backDomainFundHttp],
  'fundHttps': [domainFundHttps, backDomainFundHttps],
  'lefuHttp': [domainLefuHttp, backDomainLefuHttp],
  'lefuHttps': [domainLefuHttps, backDomainLefuHttps],
  'investorHttp': [domainInvestorHttp, backDomainInvestorHttp],
  'investorHttps': [domainInvestorHttps, backDomainInvestorHttps],
  'eipoHttp': [domainEipoHttp, backDomainEipoHttp],
  'eipoHttps': [domainEipoHttps, backDomainEipoHttps],
  'rasHttp': [domainChinextHttp, backDomainChinextHttp],
  'rasHttps': [domainChinextHttps, backDomainChinextHttps],
  'reitsHttp': [domainReitsHttp, backDomainReitsHttp],
  'reitsHttps': [domainReitsHttps, backDomainReitsHttps],
  'finHttp': [domainFintechHttp, backDomainFintechHttp],
  'finHttps': [domainFintechHttps, backDomainFintechHttps],
  'gdrHttp': [domainDrHttp, backDomainDrHttp],
  'gdrHttps': [domainDrHttps, backDomainDrHttps],
  'caHttp': [domainCaHttp, backDomainCaHttp],
  'resStaticHttp': [domainResStaticHttp, backDomainResStaticHttp],
  'resStaticHttps': [domainResStaticHttps, backDomainResStaticHttps],
  'resHttp': [domainResHttp, backDomainResHttp],
  'resHttps': [domainResHttps, backDomainResHttps],
  'reportdocsStaticHttp': [domainReportdocsStaticHttp, backDomainReportdocsStaticHttp],
  'reportdocsStaticHttps': [domainReportdocsStaticHttps, backDomainReportdocsStaticHttps],
  'discStaticHttp': [domainDiscStaticHttp, backDomainDiscStaticHttp],
  'discStaticHttps': [domainDiscStaticHttps, backDomainDiscStaticHttps],
  'docsStaticHttp': [domainDocsStaticHttp, backDomainDocsStaticHttp],
  'docsStaticHttps': [domainDocsStaticHttps, backDomainDocsStaticHttps]
};

var szseDomianReg = /([a-zA-Z0-9][-a-zA-Z0-9]{0,62})((\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+)\.?(:\d+)?/;
var pathObj = {
  main_host: domainMainHttp.match(/(.*)\/(.*)/)[2].match(szseDomianReg)[2],//主域名szse.cn
  back_host: backDomainMainHttp.match(/(.*)\/(.*)/)[2].match(szseDomianReg)[2],//备用域名sse.org.cn
  current_host: window.location.href.match(szseDomianReg)[2], //当前访问使用域名szse.cn/sse.org.cn 
  main_domain_path: domainBackSwitch('mainHttp', true), //主网站域名
  main_domain_path_http: domainBackSwitch('mainHttp'), //主网站域名(http)
  main_domain_path_https: domainBackSwitch('mainHttps'), //主网站域名(https)

  sso_domain_path_https: domainBackSwitch('sso'), //登录域名(https)

  bond_domain_path: domainBackSwitch('bondHttp', true), //固收子网站域名
  bond_domain_path_https: domainBackSwitch('bondHttps'), //固收子网站域名(https)
  bond_domain_path_http: domainBackSwitch('bondHttp'), //固收子网站域名(http)

  lefu_domain_path: domainBackSwitch('fundHttp', true), //乐富子网站域名
  lefu_domain_path_http: domainBackSwitch('fundHttp'), //乐富子网站域名(http)
  lefu_domain_path_https: domainBackSwitch('fundHttps'), //乐富子网站域名(https)

  investor_domain_path: domainBackSwitch('investorHttp', true), //投教子网站域名
  investor_domain_path_http: domainBackSwitch('investorHttp'), //投教子网站域名(http)
  investor_domain_path_https: domainBackSwitch('investorHttps'), //投教子网站域名(https)

  eipo_domain_path: domainBackSwitch('eipoHttp', true), //网下发行
  eipo_domain_path_http: domainBackSwitch('eipoHttp'), //网下发行(http)
  eipo_domain_path_https: domainBackSwitch('eipoHttps'), //网下发行(https)

  ras_domain_path: domainBackSwitch('rasHttp', true), // 注册制
  ras_domain_path_http: domainBackSwitch('rasHttp'), // 注册制（http）
  ras_domain_path_https: domainBackSwitch('rasHttps'), // 注册制（https）

  reits_domain_path: domainBackSwitch('reitsHttp', true), // 基础设施基金
  reits_domain_path_http: domainBackSwitch('reitsHttp'), // 基础设施基金（http）
  reits_domain_path_https: domainBackSwitch('reitsHttps'), // 基础设施基金（https）

  fin_domain_path: domainBackSwitch('finHttp', true), // 金融科技中心
  fin_domain_path_http: domainBackSwitch('finHttp'), // 金融科技中心（http）
  fin_domain_path_https: domainBackSwitch('finHttps'), // 金融科技中心（https）

  gdr_domain_path: domainBackSwitch('gdrHttp', true), // 互联互通存托凭证[gdr]
  gdr_domain_path_http: domainBackSwitch('gdrHttp'), // 互联互通存托凭证[gdr]
  gdr_domain_path_https: domainBackSwitch('gdrHttps'), // 互联互通存托凭证[gdr]

  ca_domain_path: domainBackSwitch('caHttp', true), // ca
  ca_domain_path_http: domainBackSwitch('caHttp'), // ca(http)

  file_path: domainBackSwitch('resStaticHttp'), //静态资源域名

  https_file_path: domainBackSwitch('resStaticHttps'), //https时静态资源域名

  report_file_path: location.protocol == 'https:' ? domainBackSwitch('reportdocsStaticHttps') : domainBackSwitch('reportdocsStaticHttp'), //报表中文件(pdf等)域名 

  disc_file_path: location.protocol == 'https:' ? domainBackSwitch('discStaticHttps') : domainBackSwitch('discStaticHttp'), //信息披露文件（pdf等）域名

  cms_file_path: location.protocol == 'https:' ? domainBackSwitch('docsStaticHttps') : domainBackSwitch('docsStaticHttp'), //cms发布的图片或视频域名


  unifieduser_path: '/api/uum', //统一用户接口
  user_path: '/api/user', //用户中心接口地址
  search_path: '/api/search', //搜索接口地址
  market_path: '/api/market', //行情接口地址
  disc_path: '/api/disc', //信息披露接口地址
  report_path: '/api/report', //报表接口地址
  bond_path: '/api/bond', //固收接口地址
  bond_report_path: '/api/bondreport', //固收子网站报表接口地址（需要登录）  
  feedback_path: '/api/feedback', //意见反馈接口地址
  apply_path: '/api/apply', //在线招聘接口地址
  investorservice_path: '/api/investorservice', //投诉举报接口地址
  szseHosts: ['big5.szse.cn']
};

for (var key in szseDomainMap) {
  szseDomainMap[key].map(function (item) {
    var host = item.match(/(.*)\/(.*)/)[2].replace(/(:\d+)/, '');
    if (pathObj.szseHosts.indexOf(host) < 0) {
      pathObj.szseHosts.push(host);
    }
  })
}

/* 
   * 主备域名切换
   * host true是否是域名；
   */
function domainBackSwitch(value, host) {
  var reg = /([a-zA-Z0-9][-a-zA-Z0-9]{0,62})((\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+)\.?(:\d+)?/;
  var _host = window.location.href.match(reg)[2];
  for (var i = 0; i < szseDomainMap[value].length; i++) {
    if (szseDomainMap[value][i].indexOf(_host) > -1) {
      return (host ? szseDomainMap[value][i].replace(/http:\/\//, '') : szseDomainMap[value][i]);
    }
  }
}

// 主网站
function mainDomainPath(type) {
  if (type == 'https:')
    return pathObj.main_domain_path_https
  else if (type == 'http')
    return pathObj.main_domain_path_http
  else
    return window.location.protocol == 'https:' ? pathObj.main_domain_path_https : pathObj.main_domain_path_http
}
// 固收
function bondDomainPath(type) {
  if (type == 'https:')
    return pathObj.bond_domain_path_https
  else if (type == 'http')
    return pathObj.bond_domain_path_http
  else
    return window.location.protocol == 'https:' ? pathObj.bond_domain_path_https : pathObj.bond_domain_path_http
}
// 基金
function fundDomainPath(type) {  
  if (type == 'https:')
    return pathObj.lefu_domain_path_https
  else if (type == 'http')
    return pathObj.lefu_domain_path_http
  else
    return window.location.protocol == 'https:' ? pathObj.lefu_domain_path_https : pathObj.lefu_domain_path_http
}

var sjsVersion = '1.2.221'; //20260829投教栏目优化


//var isDevModel = sessionStorage.getItem("isDevModel")==="true" ? true : false; //是否是开发模式

var isDevModel = false;

// 是否需要改变全文检索 搜索策略
var isNeedChangeSearchStrategy = null;
//换肤变量
//var themesColorValue = 'red';//红色red
(function () {
  'use strict';

  // 处理外链地址被转繁体版 所有以externalLink开头的全局变量

  // 外链白名单变量配置
  var externalLinkList = [
    'externalLinkLogoutHttp',
    'externalLinkIrmCnInfoHttp',
    'externalLinkBSEHttp',
    'externalLinkSSECHttp',
    'externalLinkCCMIHttp',
    'externalLinkALSHttp',
    'externalLinkWltpCnInfoHttps',
    'externalLinkCNINDEXHttp',
    'externalLinkNEEQHttp',
    'externalLinkWwwCnInfoHttp',
    'externalLinkCESCHttp',
    'externalLinkCNINFOHttp',
    'externalLinkCAPCOHttp',
    'externalLinkCSRCHttp',
    'externalLinkCXINDEXHttp',
    'externalLinkFXSHSBQYGTYYHttps',
    'externalLinkFXSHZSXMYYHttps',
    'externalLinkGSGLXCGTYYZBHttps',
    'externalLinkGSGLXCGTYYCYBHttps',
    'externalLinkZQSCYWZXYYHttps',
    'restrictedListingCommitteeTypesParam',//注册制-项目动态-再融资详情-上市委会议相关的受限类型
    'externalLinkSmeHttps',//通行证-中小企业直接入口
  ];

  var targetRegex = /big5\.szse\.cn\/site\/cht\//g;

  // 替换
  if (window.location.href.indexOf('big5.szse.cn/') > -1) {
    externalLinkList.forEach(function (varName) {
      if (window.hasOwnProperty(varName)) {
        var val = window[varName];
        if (typeof val === 'string' && val.indexOf('big5.szse.cn/site/cht/') !== -1) {
          var newVal = val.replace(targetRegex, '');
          if (val !== newVal) {
            window[varName] = newVal;
          }
        }
      }
    });
  }
})();
// 获取菜单导航
(function () {
  /**
   * navType:header/footer;isSite:www下的子站无独立域名
   * hasHostPath：true/false置标返回路径带有当前host标识eg:大湾区/bond/bayarea/index/index.html"
   */
  window.navMenuAJAX = function (menuUrl, big5MenuUrl, navType, host, isSite, hasHostPath) {
    if (location.host.indexOf(host) > -1) {
      menuUrl = location.protocol + '//' + location.host + menuUrl;
    } else {
      menuUrl = location.protocol + '//' + location.host + big5MenuUrl;
    }

    if (navType == 'header') {
      var obj = {
        url: menuUrl,
        success: function (data) {
          document.write(data);
          setPCMenuActive(host, isSite);
          setMobileMenuActive(host, isSite, hasHostPath);
        }
      }
    } else if (navType == 'footer' || navType == 'footerMenu') {
      var obj = {
        url: menuUrl,
        success: function (data) {
          if (host == 'bond') {
            var footerMenuList = parseDom(data);
            var footerMenu = window.location.protocol == 'http:' ? footerMenuList[0].innerHTML : footerMenuList[1].innerHTML;
            document.write(footerMenu);
          } else {
            document.write(data);
          }
        }
      }
    }


    var xhr = new XMLHttpRequest();

    xhr.onreadystatechange = function () {
      if (xhr.readyState === 4) {
        if (xhr.status === 200) {
          var response;
          var type = xhr.getResponseHeader('Content-Type');

          if (type.indexOf('application/json') > -1) {
            response = JSON.parse(xhr.responseText);
          } else {
            response = xhr.responseText;
          }
          obj.success && obj.success(response);
        }
      }
    }
    xhr.open('GET', obj.url, false);
    xhr.send();
  };

  function setPCMenuActive(host, isSite) {
    // 初始化PC端菜单选择样式
    var navbarNavList = document.querySelectorAll('.navbar-wrap .navbar-nav>li>a');
    if (navbarNavList.length === 0)
      return;
    var navDataPathArr = [];
    var isPCHome = true;//是否是首页
    for (var i = 0; i < navbarNavList.length; i++) {
      var datapath = navbarNavList[i].attributes['datapath'].nodeValue;
      navDataPathArr.push(datapath);
    }

    // (解决用户入口跳转投教、固收子网 域名为www问题,遗留缺陷修改后，可删除）xxmeng 20201222
    var isNotOwnerHostFlag = false;
    if (host == 'investor' || host == 'bond') {
      isNotOwnerHostFlag = (window.location.href.indexOf(host + pathObj.current_host) > 0) ? false : true;
    }

    if (window.location.href.indexOf('big5.szse.cn/') > -1) {
      if (isSite || isNotOwnerHostFlag) {
        var _href = window.location.href.split('/')[7];
      } else {
        if (host === 'eipo' && window.location.protocol == 'https:') {
          var _href = window.location.href.indexOf('/eipo/') > -1 ? window.location.href.split('/')[7] : window.location.href.split('/')[6];
        } else {
          var _href = window.location.href.split('/')[6];
        }
      }
    } else {
      if (isSite || isNotOwnerHostFlag) {
        var _href = window.location.href.split('/')[4];
      } else {
        if (host === 'eipo' && window.location.protocol == 'https:') {
          var _href = window.location.href.indexOf('/eipo/') > -1 ? window.location.href.split('/')[4] : window.location.href.split('/')[3];
        } else {
          var _href = window.location.href.split('/')[3];
        }
      }
    }
    for (var i = 0; i < navDataPathArr.length; i++) {
      if (navDataPathArr[i] && navDataPathArr[i] == _href) {
        isPCHome = false;
        document.querySelector('a[datapath="' + navDataPathArr[i] + '"]').parentNode.setAttribute('class', 'active');
      }
    }
    if (isPCHome) {
      navbarNavList[0].parentNode.setAttribute('class', 'active');
    }
  }

  function setMobileMenuActive(host, isSite, hasHostPath) {
    // 初始化菜单选中样式
    var mobileNavList = document.querySelectorAll('#dl-menu .dl-menu a');
    if (mobileNavList.length === 0)
      return;
    var isMobileHome = true;//是否是首页
    // 繁/简体版地址处理
    if (window.location.href.indexOf('big5.szse.cn/') > -1) {
      var _locationMobileHref = parseBig5Url(window.location.href, host);
    } else {
      var _locationMobileHref = parseUrl(window.location.pathname, host);
    }
    if (host == 'eipo' && window.location.protocol == 'http:') {
      _locationMobileHref = '/eipo' + _locationMobileHref;
    };
    _locationMobileHref = hasHostPath ? '/' + host + _locationMobileHref : _locationMobileHref;
    for (var i = 0; i < mobileNavList.length - 4; i++) {
      if (mobileNavList[i].getAttribute('href').indexOf('big5.szse.cn/') > -1) {
        mobileNavList[i]._href = parseBig5Url(mobileNavList[i].getAttribute('href'),host);
      } else {
        mobileNavList[i]._href = parseUrl(mobileNavList[i].getAttribute('href'));
      }
      if (_locationMobileHref == mobileNavList[i]._href) {
        isMobileHome = false;
        var activeLiList = getParent(mobileNavList[i], 'LI', 10);
        activeLiList.map(function (item, index) {
          item.setAttribute('class', 'dl-subview');
        });
        activeLiList[0].setAttribute('class', 'active');
        if (activeLiList[1]) {
          activeLiList[1].setAttribute('class', 'dl-subviewopen');
          document.getElementsByClassName('dl-menu')[0].setAttribute('class', 'dl-menu dl-subview');
        };
      }
    }

    if (isMobileHome) {
      mobileNavList[0].parentNode.setAttribute('class', 'active');
    }
  }

  function parseBig5Url(url, param) {
    // 繁体版
    if (url.indexOf('big5.szse.cn/') > -1) {
      url = url.replace(location.origin, '').replace('/site/cht/' + param + '.szse.cn/', '/');
     
      if (param == 'bond' && window.location.protocol == 'https:') {
        if (url.indexOf('/index.html?') > -1) {
          var i = url.indexOf('/index.html?');
          url = url.substring(0, i + 11);
        }
      }
      var index = url.lastIndexOf('/');
      url = url.substring(0, index + 1);
      return url;
    }
  }

  function parseUrl(url, param) {
    if (param == 'bond' && window.location.protocol == 'https:') {
      if (url.indexOf('/index.html?') > -1) {
        var i = url.indexOf('/index.html?');
        url = url.substring(0, i + 11);
      }
    }
    var index = url.lastIndexOf('/');
    url = url.substring(0, index + 1);
    return url;
  }


  function parseDom(str) {
    var objEle = document.createElement('div');
    objEle.innerHTML = str;
    return objEle.childNodes;
  }


  function getParent(ele, TagName, n) {
    var flag = true;
    var tagNameList = [];
    while (ele && n && flag) {
      ele = ele.parentNode;
      if (ele.tagName === 'BODY') {
        ele = null;
      } else if (ele.tagName === TagName) {
        tagNameList.push(ele);
      }
      n--;
    }
    return tagNameList;
  }
})();

var ie8suppose = false;  //TODO
isIE8();
// isIE8Tip();

//加载公共的css文件
window.addComCssFile = function() {
    
    if (!isDevModel) {
        changeVertion('/lib/szsewebui/szsewebui_v1.2.4-beta7/libs/libs.min.css', 'css');
        changeVertion('/lib/szsewebui/szsewebui_v1.2.4-beta7/framework/szsewebui.min.css', 'css');
        changeVertion('/common/css/dlmenu.min.css', 'css');
        changeVertion('/common/css/concatCss.min.css', 'css');
    } else {
        changeVertion('/lib/szsewebui/szsewebui_v1.2.4-beta7/libs/libs.min.css', 'css');
        changeVertion('/lib/szsewebui/szsewebui_v1.2.4-beta7/framework/szsewebui.min.css', 'css');
        changeVertion('/common/css/dlmenu.css', 'css');
        changeVertion('/common/css/reset.css', 'css');
        changeVertion('/common/css/grid.css', 'css');
        changeVertion('/common/css/week.css', 'css');
        changeVertion('/common/css/resetcontrols.css', 'css');
        changeVertion('/common/css/common.css', 'css');
    }   
   
};
//加载公共的js文件
window.addComJsFile = function() {
    if (!isDevModel) {
        changeVertion('/lib/jQuery_3.5.0/jquery.min.js', 'js');
        changeVertion('/lib/szsewebui/szsewebui_v1.2.4-beta7/framework/szsewebui.min.js', 'js');
        changeVertion('/lib/lodash/lodash.min.js', 'js');
        changeVertion('/lib/modernizr.custom.min.js', 'js');
        changeVertion('/lib/jquery.dlmenu.min.js', 'js');
        changeVertion('/lib/qrcode/jquery.qrcode.min.js', 'js');      
        changeVertion('/common/js/zhConvert.js','js');
        changeVertion('/common/js/concatJs.min.js','js');
        changeVertion('/common/js/feedback.js', 'js');      
        changeVertion('/common/js/tranbig5.min.js', 'js');      
        changeVertion('/common/js/plugins.min.js', 'js');     
    } else {
        changeVertion('/lib/jQuery_3.5.0/jquery.min.js', 'js');
        changeVertion('/lib/szsewebui/szsewebui_v1.2.4-beta7/framework/szsewebui.js', 'js');
        changeVertion('/lib/lodash/lodash.min.js', 'js');  
        changeVertion('/lib/modernizr.custom.min.js', 'js');
        changeVertion('/lib/jquery.dlmenu.min.js', 'js');
        changeVertion('/lib/qrcode/jquery.qrcode.min.js', 'js'); 
        changeVertion('/common/js/zhConvert.js','js');
        changeVertion('/common/js/utils.js', 'js');
        changeVertion('/common/js/weekpicker.js', 'js');
        changeVertion('/common/js/placeholder.js', 'js');
        changeVertion('/common/js/searchHint.js', 'js');
        changeVertion('/common/js/loading.js', 'js');
        changeVertion('/common/js/http.js', 'js');
        changeVertion('/common/js/common.js', 'js');
        changeVertion('/common/js/modal.js', 'js');    
        changeVertion('/common/js/paginator.js', 'js'); 
        changeVertion('/common/js/feedback.js', 'js');    
        changeVertion('/common/js/waterFall.js', 'js');
        changeVertion('/common/js/editSubsiteLink.js', 'js');
        changeVertion('/common/js/tranbig5.js', 'js');
        changeVertion('/common/js/plugins.js', 'js');
    }
};

//更改版本
var themesColorValue = themesColorValue || '';
function changeVertion(url, type) {

    //ie8
    // alert(ie8suppose);
    // var ie8suppose = true;
  //isIE8();
    //ie8 end
    // var ie8suppose = true;
    var filePath = '';
    if (isNotHttps()) {
        filePath = pathObj.https_file_path;
    } else {
        filePath = pathObj.file_path;
    }

    if(!isDevModel){
        var minFlag = (url.indexOf('.min.'+type)>-1);//url中是否带有'min';
        //var libFlag = url.indexOf('/lib')>-1;//url中是否带有lib;
        if(!minFlag)url=url.replace('.'+type,'.min.'+type);//当isDevModel=false时即非开发环境，此时则引用压缩文件（即带min）
    }

    switch (type) {
        case 'css':
            //url = 'themes/' + themesColorValue + url;
            if(themesColorValue.length!== 0 && url.indexOf("/lib/")==-1 && url.indexOf("ie8fix")==-1 ){
            	var urlname = url.indexOf(".");
            	url = url.substring(0,urlname) + "_" + themesColorValue + url.substring(urlname);
            }
            //var linkhref = " <link rel='stylesheet' href='" + filePath + url + "?version=" + sjsVersion + "' /> ";
            // if(url.indexOf("SuniT")> 0)
            // var linkhref = " <link rel='stylesheet' href='" + url + "?version=" + sjsVersion + "' /> ";
            // else
            var linkhref = " <link rel='stylesheet' href='" + filePath + url + "?version=" + sjsVersion + "' /> ";
            // 
            if(ie8suppose){
                linkhref = " <link rel='stylesheet' href='" + url + "?version=" + sjsVersion + "' /> ";
            }
            document.write(linkhref);
            break;
        case 'js':
            //var jshref=" <script src='" + filePath + url + "?version=" + sjsVersion + "'> <\/script> ";
            // if(url.indexOf("SuniT")> 0)
            // var jshref =" <script src='" + url + "?version=" + sjsVersion + "'> <\/script> ";
            // else
            var jshref =" <script src='" + filePath + url + "?version=" + sjsVersion + "'> <\/script> ";

            // tranbig5不加繁体版域名,解决固收信用保护凭证文章繁体版检索  xxmeng
            if(url == '/common/js/tranbig5.min.js'){
              jshref=jshref.replace(/big5.szse.cn\/site\/cht\//,"");
            }
            document.write(jshref);
            break;
    }
}

//判断当前地址是http还是https
function isNotHttps() {
    var href = window.location.href;
    var index = href.indexOf("//");
    var str = href.substring(0, index - 1);
    if (str == 'https') {
        return true;
    } else {
        return false;
    }
}

function isIE8(){
   
    var DEFAULT_VERSION = 8.0;  
    var ua = navigator.userAgent.toLowerCase();  
    var isIE = ua.indexOf("msie")>-1;  
    var safariVersion;  
    if(isIE){  
    safariVersion =  ua.match(/msie ([\d.]+)/)[1];  
    }  
    if(safariVersion <= DEFAULT_VERSION ){  
        ie8suppose = true;
       //alert('系统检测到您正在使用ie8以下内核的浏览器');
        var ieTipStr = '<div class="low_version">系统检测到您正在使用ie8以下内核的浏览器，不能实现完美体验，请及时更新浏览器版本！</div>'; 
        // document.write = urite;
        // document.write(ieTipStr);
        // var oDiv = document.createElement("div");
        // // oDiv.class="low_version";
        // var oDivText = document.createTextNode("ie8以下内核!!!!");
        // oDiv.appendChild(oDivText);
        // // document.body.insertBefore(oDiv,document.body.firstElementChild);
        // document.body.appendChild(oDiv);
        // document.getElementByTagName("div")[0].className="low_version";
    };
    //return ie8suppose;
}


// function isIE8Tip(){
   
//     var DEFAULT_VERSION = 8.0;  
//     var ua = navigator.userAgent.toLowerCase();  
//     var isIE = ua.indexOf("msie")>-1;  
//     var safariVersion;  
//     if(isIE){  
//     safariVersion =  ua.match(/msie ([\d.]+)/)[1];  
//     }  
//     if(safariVersion <= DEFAULT_VERSION ){  
//         // alert('系统检测到您正在使用ie8以下内核的浏览器');

//     };
//     //return ie8suppose;
// }