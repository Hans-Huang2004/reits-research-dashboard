//获取请求值
var getValue = function(pram1) {
	var str = window.location.search;
	if (str.indexOf(pram1) != -1) {
		var pos_start = str.indexOf(pram1) + pram1.length + 1;
		var pos_end = str.indexOf('&', pos_start);
		if (pos_end == -1) {
			return str.substring(pos_start);
		} else {
			return str.substring(pos_start, pos_end);
		}
	} else {
		return '';
	}
};

//表格点击事件
function tdclickable() {
	// 阻止表格文字复制跳转
	;
	(function preventLinks() {
		//表格点击事件
		var jumpstates = true;
		$(".tdclickable").each(function(index, elem) {

			var mouseX1, mouseY1;
			var mouseX2, mouseY2;
			$(elem).find("tr").each(function(i, el) {
				var $this = $(el);
				var $links = $this.find("a");

				if (jQBrowser.mobile) {
					$links.removeAttr('target');
				}

				if ($links.length == 1) {
					$this.addClass("isClickTr");
				}
			});


			$(elem).on("mousedown", ".isClickTr", function(e) {
				jumpstates = true;
				mouseX1 = e.pageX;
				mouseY1 = e.pageY;
				$(this).one("mousemove", function() {

					$(this).one("mouseup", function(e) {
						mouseX2 = e.pageX;
						mouseY2 = e.pageY;
						var _nums1 = Math.abs(mouseX1 - mouseX2);
						var _nums2 = Math.abs(mouseY1 - mouseY2);
						if (_nums1 >= 12 || _nums2 >= 12) {
							jumpstates = false;
						}
					});
				});
			});
		});

		$(".tdclickable").unbind('click').on('click', 'tr', function(e) {
			var $this = $(this);
			var $links = $this.find("a");
			$links.wrapInner("<span>");
			if ($links.length == 1 && jumpstates === true) {
				$links.find("span").eq(0).click();
				e.stopPropagation();
			}
		}).on("click", "a", function(e) {
			e.stopPropagation();
		});
	})();
}

var getValueByRestful = function(
pram) { //参数格式  eg: http://127.0.0.1/?key/value/key1/value1      getValueByRestful('key') / value、getValueByRestful('key1') / value1 切记   参数名不能相同 
	var reg = new RegExp('(^|/)' + pram + '(/|$)([^/]*)(/|$)', 'i');
	var r = window.location.search.substr(1).match(reg);
	return (r != null ? decodeURI(r[3]) : '');
};

function stringForZero(d) {
	if (d == null || d == undefined || d == 'null' || '' == d || '-' == d || '.00' == $.trim(d) || '0.00' == d ||
		' .00' == d) {
		return '0';
	} else {
		return d;
	}
}

// 静态分页
var getPage = function(obj) {
	if (obj.pageType == 'WCM') {
		if (obj.pageCount == 1) {
			obj.pageId.hide();
		} else {
			obj.pageId.show();
		}
	}
	var $this = this;
	this._createPage = function(obj) {
		var total_page = parseInt(obj.pageCount); //总页数
		if (obj.isStatic) { //判断处理WCM当前页面
			if (obj.pageIndex == 0) {
				obj.pageIndex = 1;
			} else {
				obj.pageIndex = obj.pageIndex + 1;
			}
		}
		if (obj.ajaxDataType == 'xml') { //判断处理WCM当前页面
			if (obj.pageIndex == 0) {
				obj.pageIndex = 1;
			}
		}
		var current_page = parseInt(obj.pageIndex); //当前页数

		var pager_length = obj.pageLength; //不包next 和 prev 必须为奇数
		var pager = new Array(pager_length);
		var header_length = obj.headerKeep; //头部预留页码
		var tailer_length = obj.footerKeep; //尾部预留页码
		//header_length + tailer_length 必须为偶数
		var main_length = pager_length - header_length - tailer_length; //必须为奇数
		var tagStr = obj.tagStr;
		var tagStr2 = obj.tagStr2;
		var classStr = obj.classStr;
		var idStr = obj.idStr;
		var nameStr = obj.nameStr;
		var disable_class = obj.disable;
		var select_class = obj.active;
		var extClass = obj.extClass;
		var i;
		var code = '';
		var mobileCode = '';
		var codeList = [];
		var numRel = '';

		if (total_page < current_page) {
			//alert('总页数不能小于当前页数');
			return false;
		}
		//判断总页数是不是小于 分页的长度，若小于则直接显示
		if (total_page <= pager_length) {
			for (i = 0; i < total_page; i++) {
				code += (i + 1 != current_page) ? $this.createTag({
					pageName: obj.pageName,
					pageExt: obj.pageExt,
					isStatic: obj.isStatic,
					tagStr: tagStr,
					classStr: classStr,
					idStr: idStr,
					nameStr: nameStr,
					a_html: i + 1
				}) : $this.createTag({
					pageName: obj.pageName,
					pageExt: obj.pageExt,
					isStatic: obj.isStatic,
					tagStr: tagStr,
					classStr: select_class,
					idStr: idStr,
					nameStr: nameStr,
					a_html: i + 1
				});
			}
		} else { //如果总页数大于分页长度，则为一下函数
			//先计算中心偏移量
			var offset = (pager_length - 1) / 2;
			//分三种情况，第一种左边没有...
			if (current_page <= offset + 1) {
				var tailer = '';
				//前header_length + main_length 个直接输出之后加一个...然后输出倒数的    tailer_length 个
				for (i = 0; i < header_length + main_length; i++) {
					code += (i + 1 != current_page) ? $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: classStr,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i + 1
					}) : $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: select_class,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i + 1
					});
				}
				code += $this.createTag({
					pageName: obj.pageName,
					pageExt: obj.pageExt,
					isStatic: obj.isStatic,
					tagStr: tagStr,
					classStr: classStr,
					idStr: idStr,
					nameStr: nameStr,
					a_html: '...'
				});
				for (i = total_page; i > total_page - tailer_length; i--) {
					tailer = $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: classStr,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i
					}) + tailer;
				}
				code += tailer;
			} else if (current_page >= total_page - offset) { //第二种情况是右边没有...
				var header = '';
				//后tailer_length + main_length 个直接输出之前加一个...然后拼接 最前面的 header_length 个
				for (i = total_page; i >= total_page - main_length - 1; i--) {
					code = ((current_page != i) ? $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: classStr,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i
					}) : $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: select_class,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i
					})) + code;
				}
				if (total_page != (pager_length + 1)) {
					code = $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: classStr,
						idStr: idStr,
						nameStr: nameStr,
						a_html: '...'
					}) + code;
				}
				for (i = 0; i < header_length; i++) {
					header += $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: classStr,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i + 1
					});
				}
				code = header + code;
			} else { //最后一种情况，两边都有...
				var header = '';
				var tailer = '';
				//首先处理头部
				for (i = 0; i < header_length; i++) {
					header += $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: classStr,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i + 1
					});
				}
				header += $this.createTag({
					pageName: obj.pageName,
					pageExt: obj.pageExt,
					isStatic: obj.isStatic,
					tagStr: tagStr,
					classStr: classStr,
					idStr: idStr,
					nameStr: nameStr,
					a_html: '...'
				});
				//处理尾巴
				for (i = total_page; i > total_page - tailer_length; i--) {
					tailer = $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: classStr,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i
					}) + tailer;
				}
				tailer = $this.createTag({
					pageName: obj.pageName,
					pageExt: obj.pageExt,
					isStatic: obj.isStatic,
					tagStr: tagStr,
					classStr: classStr,
					idStr: idStr,
					nameStr: nameStr,
					a_html: '...'
				}) + tailer;
				//处理中间
				//计算main的中心点
				var offset_m = (main_length - 1) / 2;
				var partA = '';
				var partB = '';
				var j;
				var counter = (parseInt(current_page) + parseInt(offset_m));
				for (i = j = current_page; i <= counter; i++, j--) {
					partA = ((i == j) ? '' : $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: classStr,
						idStr: idStr,
						nameStr: nameStr,
						a_html: j
					})) + partA;
					partB += (i == j) ? $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: select_class,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i
					}) : $this.createTag({
						pageName: obj.pageName,
						pageExt: obj.pageExt,
						isStatic: obj.isStatic,
						tagStr: tagStr,
						classStr: classStr,
						idStr: idStr,
						nameStr: nameStr,
						a_html: i
					});
				}
				//拼接
				code = header + partA + partB + tailer;

			}
		}

		var prev = (current_page == 1) ? $this.createTag({
			pageName: obj.pageName,
			pageExt: obj.pageExt,
			isStatic: obj.isStatic,
			tagStr: tagStr,
			classStr: disable_class,
			idStr: idStr,
			nameStr: nameStr,
			a_html: obj.prevName,
			classPage: obj.classPage
		}) : $this.createTag({
			pageName: obj.pageName,
			pageExt: obj.pageExt,
			isStatic: obj.isStatic,
			tagStr: tagStr,
			classStr: classStr,
			idStr: idStr,
			nameStr: nameStr,
			a_html: obj.prevName,
			classPage: obj.classPage
		});

		var prev2 = (current_page == 1) ? $this.createTag2({
			pageName: obj.pageName,
			pageExt: obj.pageExt,
			isStatic: obj.isStatic,
			tagStr: tagStr,
			tagStr2: tagStr2,
			classStr: disable_class,
			idStr: idStr,
			nameStr: nameStr,
			a_html: obj.prevName2,
			classPage: obj.classPage
		}) : $this.createTag2({
			pageName: obj.pageName,
			pageExt: obj.pageExt,
			isStatic: obj.isStatic,
			tagStr: tagStr,
			tagStr2: tagStr2,
			classStr: classStr,
			idStr: idStr,
			nameStr: nameStr,
			a_html: obj.prevName2,
			classPage: obj.classPage
		});

		if (1 != current_page) {
			prev = (current_page == 1) ? $this.createTag({
				pageName: obj.pageName,
				pageExt: obj.pageExt,
				isStatic: obj.isStatic,
				tagStr: tagStr,
				classStr: disable_class,
				idStr: idStr,
				nameStr: nameStr,
				a_html: obj.prevName,
				pageIndex: current_page,
				classPage: obj.classPage
			}) : $this.createTag({
				pageName: obj.pageName,
				pageExt: obj.pageExt,
				isStatic: obj.isStatic,
				tagStr: tagStr,
				classStr: classStr,
				idStr: idStr,
				nameStr: nameStr,
				a_html: obj.prevName,
				pageIndex: (current_page - 1),
				classPage: obj.classPage
			});
			prev2 = (current_page == 1) ? $this.createTag2({
				pageName: obj.pageName,
				pageExt: obj.pageExt,
				isStatic: obj.isStatic,
				tagStr: tagStr,
				tagStr2: tagStr2,
				classStr: disable_class,
				idStr: idStr,
				nameStr: nameStr,
				a_html: obj.prevName2,
				pageIndex: current_page,
				classPage: obj.classPage
			}) : $this.createTag2({
				pageName: obj.pageName,
				pageExt: obj.pageExt,
				isStatic: obj.isStatic,
				tagStr: tagStr,
				classStr: classStr,
				idStr: idStr,
				nameStr: nameStr,
				a_html: obj.prevName2,
				pageIndex: (current_page - 1),
				classPage: obj.classPage
			});
		}
		var next = (current_page == total_page) ? $this.createTag({
			pageName: obj.pageName,
			pageExt: obj.pageExt,
			isStatic: obj.isStatic,
			tagStr: tagStr,
			classStr: disable_class,
			idStr: idStr,
			nameStr: nameStr,
			a_html: obj.nextName,
			classPage: obj.classPage
		}) : $this.createTag({
			pageName: obj.pageName,
			pageExt: obj.pageExt,
			isStatic: obj.isStatic,
			tagStr: tagStr,
			classStr: classStr,
			idStr: idStr,
			nameStr: nameStr,
			a_html: obj.nextName,
			classPage: obj.classPage
		});
		var next2 = (current_page == total_page) ? $this.createTag2({
			pageName: obj.pageName,
			pageExt: obj.pageExt,
			isStatic: obj.isStatic,
			tagStr: tagStr,

			classStr: disable_class,
			idStr: idStr,
			nameStr: nameStr,
			a_html: obj.nextName2,
			classPage: obj.classPage
		}) : $this.createTag2({
			pageName: obj.pageName,
			pageExt: obj.pageExt,
			isStatic: obj.isStatic,
			tagStr: tagStr,
			tagStr2: tagStr2,
			classStr: classStr,
			idStr: idStr,
			nameStr: nameStr,
			a_html: obj.nextName2,
			classPage: obj.classPage
		});
		if (obj.pageCount != current_page) {
			next = (current_page == total_page) ? $this.createTag({
				pageName: obj.pageName,
				pageExt: obj.pageExt,
				isStatic: obj.isStatic,
				tagStr: tagStr,
				classStr: disable_class,
				idStr: idStr,
				nameStr: nameStr,
				a_html: obj.nextName,
				pageIndex: current_page,
				classPage: obj.classPage
			}) : $this.createTag({
				pageName: obj.pageName,
				pageExt: obj.pageExt,
				isStatic: obj.isStatic,
				tagStr: tagStr,
				classStr: classStr,
				idStr: idStr,
				nameStr: nameStr,
				a_html: obj.nextName,
				pageIndex: (current_page + 1),
				classPage: obj.classPage
			});
			next2 = (current_page == total_page) ? $this.createTag2({
				pageName: obj.pageName,
				pageExt: obj.pageExt,
				isStatic: obj.isStatic,
				tagStr: tagStr,

				classStr: disable_class,
				idStr: idStr,
				nameStr: nameStr,
				a_html: obj.nextName2,
				pageIndex: current_page,
				classPage: obj.classPage
			}) : $this.createTag2({
				pageName: obj.pageName,
				pageExt: obj.pageExt,
				isStatic: obj.isStatic,
				tagStr: tagStr,
				classStr: classStr,
				idStr: idStr,
				nameStr: nameStr,
				a_html: obj.nextName2,
				pageIndex: (current_page + 1),
				classPage: obj.classPage
			});
		}

		var codebutton = '<li><button page="' + obj.pageCount +
			'" id="pagebutton" class="search"><i class="fe fe-search"></i></button></li>'
		var codeinputone =
			'<li><input id="htcodeinput"  class="codeinput1 search_input"  type="text" value="">页</li>';
		code = prev + code + next + codeinputone + codebutton;
		var tempPrev = $(prev).find('a');
		var tempNext = $(next).find('a');
		var mobilePrev = '<button type="button" page="' + tempPrev.attr("page") +
			'" class="btn btn-default navbar-btn ' + tempPrev.attr("class") + '">上一页</button>';
		var mobileNext = '<button type="button" page="' + tempNext.attr("page") +
			'" class="btn btn-default navbar-btn next-page ' + tempNext.attr("class") + '">下一页</button>';
		mobileCode = mobilePrev + mobileNext;

		codeList.push(code);
		codeList.push(mobileCode);
		return codeList;

	}
	/**
	 * 计算分页URL值
	 */
	this._makeUrl = function(obj) {
		var _dataUrl = obj.dataUrl;
		var _pageIndex = obj.pageIndex;
		_dataUrl = _dataUrl.replace(".shtml", '_' + _pageIndex + '.shtml');
		if (_pageIndex > 1) {
			_dataUrl = _dataUrl.replace(_dataUrl.substring(_dataUrl.lastIndexOf("_")), '_' + _pageIndex +
				'.shtml');
		} else {
			_dataUrl = _dataUrl.replace(_dataUrl.substring(_dataUrl.lastIndexOf("_")), '.shtml');
		}
		return _dataUrl;
	}
	/**
	 *  数据的填充
	 */
	this._showData = function(obj) {
		var $pageData = $(obj.pageData);
		$pageData.html("")
		for (var i = 0; i < xmlData.length-1; i++) {
			var strHTML = obj.ajaxData(xmlData[i]);
			$pageData.append(strHTML);
		}
		$pageData.find("a[href^='javascript']").each(function() {
			$(this).parent().html($(this).text());
			// console.log("a[href^='javascript']  this1");
		});
		tdclickable();

	}


	var xmlData = [];
	/**
	*   请求数据
	    " style="display:none" ="20"  ="1" PAGE_NAME='/aboutus/mediacenter/hotandd/data' PAGE_EXT='htm' ></div>
	    */
	this._getData = function(obj) {
		$.ajax({
			type: obj.ajaxType,
			dataType: obj.ajaxDataType,
			url: $this._makeUrl(obj)+ "?v="+Math.random(),
			success: function(xml) {
				var tempitem = $(xml).find("#createPage").attr("rel");
				// Li.chen  2016-12-07 11:46:35
				// if(tempitem != undefined){
				//  xmlData = $(xml).find(tempitem);
				// }else{
				//  xmlData = $(xml).find("dl");
				// }

				if (tempitem != undefined) {
					xmlData = $(xml).find(tempitem);
				}
				if ($(xml).find("dl").length > 0) {
					xmlData = $(xml).find("dl");
				} else if ($(xml).find("ul").length > 1) {
					xmlData = $(xml).find("ul:first");
				}

				obj.pageIndex = staticPage.PageCount;
				obj.pageCount = staticPage.PageIndex;

				$this._showData(obj);
			},
			error: function(xml) {
				xmlData = null;
			}
		});
	}
	//创建标签
	this.createTag = function(obj) {
		classStr = (obj.classStr == '') ? '' : ' class="' + obj.classStr + '"';
		idStr = (obj.idStr == '') ? '' : ' id="' + obj.idStr + '"';
		nameStr = (obj.nameStr == '') ? '' : ' name="' + obj.nameStr + '"';
		//获取html
		var extStr = null;

		if (!isNaN(obj.a_html)) {
			numRel = 'page="' + obj.a_html + '"';
		} else {
			numRel = '';
		}

		var code = '';

		//判断是否上一页下一页
		if (obj.pageIndex != undefined) {
			numRel = 'page="' + obj.pageIndex + '"';
			var classPage = ' class="' + obj.classPage + '"';

			if (obj.tagStr == 'a') {
				if (obj.isStatic) {
					//
					if (obj.pageIndex == 1) {
						extStr = obj.pageName + "." + obj.pageExt;
					} else {
						extStr = obj.pageName + "_" + (obj.pageIndex - 1) + "." + obj.pageExt;
					}
					code = '<li page="page"><' + obj.tagStr + classPage + idStr + numRel + nameStr + ' href="' +
						extStr + '">' + obj.a_html + '</' + obj.tagStr + '></li>';
				} else {
					code = '<li page="page"><' + obj.tagStr + classPage + idStr + numRel + nameStr +
						' href="javascript:;">' + obj.a_html + '</' + obj.tagStr + '></li>';
				}
			} else {
				code = '<li page="page"><' + obj.tagStr + classPage + idStr + numRel + nameStr + ' >' + obj
					.a_html + '</' + obj.tagStr + '></li>';

			}
		} else {
			if (obj.tagStr == 'a') {
				if (obj.isStatic) {
					if (numRel) {
						if (obj.a_html == 1) {
							extStr = obj.pageName + "." + obj.pageExt;
						} else {
							extStr = obj.pageName + "_" + (obj.a_html - 1) + "." + obj.pageExt;
						}
					} else {
						extStr = "javascript:;";
					}

					code = '<li page="page"><' + obj.tagStr + classStr + idStr + numRel + nameStr + ' href="' +
						extStr + '">' + obj.a_html + '</' + obj.tagStr + '></li>';
				} else {
					code = '<li page="page"><' + obj.tagStr + classStr + idStr + numRel + nameStr +
						' href="javascript:;">' + obj.a_html + '</' + obj.tagStr + '></li>';
				}
			} else {
				code = '<li page="page"><' + obj.tagStr + classStr + idStr + numRel + nameStr + ' >' + obj
					.a_html + '</' + obj.tagStr + '></li>';

			}
		}

		return code;
	}

	this.createTag2 = function(obj) {
		var mobileCode = '';


		classStr = (obj.classStr == '') ? '' : ' class="' + obj.classStr + '"';
		idStr = (obj.idStr == '') ? '' : ' id="' + obj.idStr + '"';
		nameStr = (obj.nameStr == '') ? '' : ' name="' + obj.nameStr + '"';



		//获取html
		var extStr = null;

		if (isNaN(obj.a_html)) {
			numRel = 'page="' + obj.pageIndex + '"';
		} else {
			numRel = '';
		}

		//判断是否上一页下一页
		if (obj.pageIndex != undefined) {
			numRel = 'page="' + obj.pageIndex + '"';
			var classPage = ' class="' + obj.classPage + '"';

			if (obj.tagStr == 'a') {
				if (obj.isStatic) {
					//
					if (obj.pageIndex == 1) {
						extStr = obj.pageName + "." + obj.pageExt;
					} else {
						extStr = obj.pageName + "_" + (obj.pageIndex - 1) + "." + obj.pageExt;
					}
					mobileCode = '<button type="button" class="btn btn-default navbar-btn ' + obj.classPage +
						'" ' + numRel + '>' + obj.a_html + '</button>';
				} else {
					//page=2
					mobileCode = '<button type="button" class="btn btn-default navbar-btn ' + obj.classPage +
						'" ' + numRel + '>' + obj.a_html + '</button>';
				}
			} else {
				mobileCode = '<button type="button" class="btn btn-default navbar-btn ' + obj.classPage + '" ' +
					numRel + '>' + obj.a_html + '</button>';
			}
		} else {
			if (obj.tagStr == 'a') {
				if (obj.isStatic) {
					if (numRel) {
						if (obj.a_html == 1) {
							extStr = obj.pageName + "." + obj.pageExt;
						} else {
							extStr = obj.pageName + "_" + (obj.a_html - 1) + "." + obj.pageExt;
						}
					} else {
						extStr = "javascript:;";
					}

					mobileCode = '<button type="button" class="btn btn-default navbar-btn ' + obj.classPage +
						'" ' + numRel + '>' + obj.a_html + '</button>';
				} else {
					//page=""
					mobileCode = '<button type="button" class="btn btn-default navbar-btn ' + obj.classPage +
						'" ' + numRel + '>' + obj.a_html + '</button>';
				}
			} else {
				mobileCode = '<button type="button" class="btn btn-default navbar-btn ' + obj.classPage + '" ' +
					numRel + '>' + obj.a_html + '</button>';

			}
		}
		//mobileCode ='<button type="button" class="btn btn-default navbar-btn '+obj.classPage+'" '+ numRel +'>'+obj.a_html+'</button>';
		if (mobileCode.indexOf("下一页") > -1) {
			mobileCode = '<button type="button" class="btn btn-default navbar-btn next-page ' + obj.classPage +
				'" ' + numRel + '>' + obj.a_html + '</button>';
		}
		return mobileCode;
	}


	if (obj.pageType == "WCM") {
		if (!obj.isStatic) {
			$this._getData(obj);
		}
	} else {
		var results = obj.ajaxData();
		if (results != null) {
			obj.pageIndex = results.pageIndex;
			obj.pageCount = results.pageCount;
		}
	}
	var pageStr = $this._createPage(obj);



	if (pageStr) {
		var $page = obj.pageId.find('.hidden-mobile');
		var $pageMobile = obj.pageId.find('.mobile-page');
		$page.html(pageStr[0]);
		$pageMobile.html(pageStr[1]); //手机分页
		//绑定点击事件
		if (!obj.isStatic) {
			$page.unbind().delegate(obj.tagStr, 'click', function() {

				if ($page.parent().parent().parent() != null && $page.parent().parent().parent().length >
					1) {
					offsetTops($page.parent().parent().parent().parent());
				} else {
					offsetTops($page.parent().parent().parent());
				};


				var $then = $(this);
				var page = $then.attr("page");
				if (page != undefined && !$then.hasClass(obj.active) && page != ' ' && page != ' ') {
					obj.pageIndex = page;
					var pageItem = $then.parent().parent().find('li');
					obj.pageCount = pageItem.eq(pageItem.length - 4).find('a').attr("page")
					pageStr = $this._createPage(obj);
					if (pageStr) {
						$page.html(pageStr[0]);
						$pageMobile.html(pageStr[1]);
					}
					if (obj.pageType == "WCM") {
						$this._getData(obj);
					} else {
						var results = {
							"pageIndex": obj.pageIndex,
							"pageCount": obj.pageCount
						};
						obj.ajaxData(results);
					}
				}
			});

			$page.delegate('#pagebutton', 'click', function(event) {
				event.stopImmediatePropagation();
				if ($page.parent().parent().parent() != null && $page.parent().parent().parent().length >
					1) {
					offsetTops($page.parent().parent().parent().parent());
				} else {
					offsetTops($page.parent().parent().parent());
				};
				var $then = $(this);
				var allpage = parseInt($then.attr("page"));
				var page = parseInt($("#htcodeinput").val());
				if (!isNaN(page)) {
					if (page > 0 && page <= allpage && page) {
						if (page != undefined && page != ' ') {
							obj.pageIndex = page;
							var pageItem = $then.parent().parent().find('li');
							obj.pageCount = pageItem.eq(pageItem.length - 4).find('a').attr("page")
							pageStr = $this._createPage(obj);
							if (pageStr) {
								$page.html(pageStr[0]);
								$pageMobile.html(pageStr[1]);
							}
							if (obj.pageType == "WCM") {
								$this._getData(obj);
							} else {
								var results = {
									"pageIndex": page,
									"pageCount": obj.pageCount
								};
								obj.ajaxData(results);
								return;
							}
						}
					} else {
						alert('请输入正确的页数!');
						return;
					}
				} else {
					alert("请输入正确的页数!");
					return;
				}

			});
			$page.delegate("#htcodeinput", "keyup", function(e) {
				var _this = $(this)
				var e = e || event,
					keycode = e.which || e.keyCode;
				if (e.keyCode == 13) {
					$("#pagebutton").trigger("click");
					_this.blur(); //处理事件
				}
			})



			$pageMobile.unbind().delegate('button', 'click', function() {

				// var top_sse_wrap_cn_con= $page.parent().parent().parent();
				// $('html,body').animate({scrollTop: top_sse_wrap_cn_con.offset().top}, 100);
				offsetTops($page.parent().parent().parent());

				var $then = $(this);
				var page = $then.attr("page");
				if (page != undefined && !$then.hasClass(obj.active) && page != ' ' && page != ' ' &&
					page != "undefined") {
					obj.pageIndex = page;
					pageStr = $this._createPage(obj);
					if (pageStr) {
						$page.html(pageStr[0]);
						$pageMobile.html(pageStr[1]);
					}
					if (obj.pageType == "WCM") {
						$this._getData(obj);
					} else {
						var results = {
							"pageIndex": obj.pageIndex,
							"pageCount": obj.pageCount
						};
						obj.ajaxData(results);
					}
				}
			});
		}
	}

}
var staticPage={};
var $pageList = $('#createPage');
if ($pageList.length > 0) {
	var $dataUrl = $pageList.attr("page_name") + ".shtml";
         staticPage.PageCount=$("#createPage").attr("page_count");
         staticPage.PageIndex=$("#createPage").attr("page_index");
	getPage({
		pageId: $('.js_pageTable'), //分页输出ID选择器
		pageData: $pageList.attr("rel"), //数据输出选择器
		headerKeep: 1, //头部预留页码数量 headerKeep + footerKeep 必须为偶数
		footerKeep: 1, //尾部预留页码数量 headerKeep + footerKeep 必须为偶数
		pageLength: 7, //页码显示数量,必须为奇数
		tagStr: 'a', //使用标签
		classStr: 'classStr', //标签class
		idStr: 'idStr', //标签id
		nameStr: 'nameStr', //标签name
		disable: 'disable', //不能点击class
		active: 'active', //标签选中class
		prevName: '上一页',
		prevName2: '上一页', //手机版的button内容
		nextName: '下一页',
		nextName2: '下一页',
		pageCount: $("#createPage").attr("page_count"),
		pageIndex: $("#createPage").attr("page_index"),
		classPage: 'classPage', //上下页class
		pageType: 'WCM', //分页类型
		ajaxData: insertItem, //异步请求
		ajaxType: 'get', //请求类型
		ajaxDataType: 'html', //数据类型
		dataUrl: $dataUrl //数据URL
	});

}

function offsetTops(id) {
	$('html,body').animate({
		scrollTop: id.offset().top
	}, 100);
}
//加载数据样式
function insertItem(data) {
	var items = $(data).html();
	/**
	 * 屏蔽“上海证券交易所”字样   小梅提
	 * @param  {[type]} $("div.sse_wrap_cn_con div.list_pxtz").length > 0 [description]
	 * @return {[type]}                        [description]
	 */
	// if ($("div.sse_wrap_cn_con div.list_pxtz").length > 0) {
	//  items = items.replace(/上海证券交易所/g,"");
	// };
	return items;
}

var Page;
(function() {
	var Page = {
		version: '1.0',
		author: ''
	};
	var showPage = 7;
	Page.navigation = function(ele, totalPage, currentPage, func) {
		currentPage = (currentPage > totalPage ? totalPage : currentPage);
		var nav = '<ul>';
		nav += (currentPage <= 1 ? '' : '<li><a class="flip" href="javascript:' + func + '(' + (currentPage -
			1) + ');" title="Previous Page">上一页</a></li>');
		var start = currentPage - Math.floor(showPage / 2),
			end = currentPage + Math.floor(showPage / 2);
		start -= (end > totalPage ? (end - totalPage) : 0)
		start = (start <= 0 ? 1 : start);
		end = ((currentPage < showPage && end < showPage) ? showPage : end);
		end = (end > totalPage ? totalPage : end);
		if (currentPage >= 5) {
			nav += '<li><a title="首页"  href="javascript:' + func + '(1);">1</a></li>';
			nav += '<li><a href="javascript:;">...</a></li>';
			start += 2;
		}
		end -= ((totalPage - currentPage) >= 5 ? 2 : 0);
		for (var i = start; i <= end; i++) {
			nav += '<li><a class="' + (i == currentPage ? 'active' : '') + '" title="转到第' + i +
				'页" href="javascript:' + func + '(' + i + ');">' + i + '</a></li>';
		}
		if ((totalPage - currentPage) >= 5) {
			nav += '<li><a href="javascript:;">...</a></li>';
			nav += '<li><a title="转到第' + totalPage + '页"  href="javascript:' + func + '(' + totalPage + ');">' +
				totalPage + '</a></li>';
		}
		nav += (currentPage >= totalPage ? '' : '<li><a class="flip" href="javascript:' + func + '(' + (
			currentPage + 1) + ');" title="下一页">下一页</a></li>');
		nav += '<li>共' + totalPage + '页&' + 'nb' + 'sp;转到第<input type="text" class="search_input ' + func +
			'_page_no" totalPage="' + totalPage + '">页</li><li><a href="javascript:' + func +
			'(0);" class="search">Go</a></li></ul>';
		$(ele).html(nav);
	};
	Page.phonenavigation = function(ele, totalPage, currentPage, func) {
		var phonenav = [];
		phonenav.push((currentPage <= 1 ? '' : (
			'<button type="button" class="btn btn-default navbar-btn" onclick="' + func + '(' + (
				currentPage - 1) + ')">上一页</button>')));
		phonenav.push((currentPage >= totalPage ? '' :
			'<button type="button" class="btn btn-default navbar-btn next-page" onclick="' + func +
			'(' + (currentPage + 1) + ')">下一页</button>'));
		$(ele).html(phonenav.join(''));
	};
	Page.setTops = function(_setTopspx) {
		$('html,body').animate({
			scrollTop: _setTopspx
		}, 10);
	};
	Page.check = function(page, func) {
		if (0 == page) {
			var _totalpage = Number($('.' + func + '_page_no').attr('totalpage'));
			var pageno = Number($.trim($('.' + func + '_page_no').val()));
			if (isPositiveInteger(pageno)) {
				page = (pageno < _totalpage ? (pageno <= 0 ? 1 : pageno) : _totalpage);
				return page;
			} else {
				alert('请输入正确的页码');
				$('.' + func + '_page_no').focus().select();
				return null;
			}
		} else {
			return page;
		}
	}
	this.Page = Page;
})();

//加载更多查询条件
function showMoreConditions() {
	if ($('#moreConditionsBtn').hasClass('btn_more1')) {
		$('#moreConditionsBtn').removeClass('btn_more1').addClass('btn_more2').find('i').removeClass('fe-plus')
			.addClass('fe-minus');
		$('#moreConditions').show();

	} else {
		$('#moreConditionsBtn').removeClass('btn_more2').addClass('btn_more1').find('i').removeClass('fe-minus')
			.addClass('fe-plus');
		$('#moreConditions').hide();
	}
};


//转义函数 
var type_transfer = function(data, isWrap) { //isWrap 是否换行
	if (data.BOND_TYPE == "0" || data.BOND_TYPE == "5") {
		return "小公募";
	} else if (data.BOND_TYPE == "1" || data.BOND_TYPE == "6") {
		return "私募";
	} else if (data.BOND_TYPE == "2") {
		return "ABS";
	} else if (data.BOND_TYPE == "3" || data.BOND_TYPE == "7") {
		return "大公募";
	} else {
		return "-";
	}
}

var contentLink1 = function(data) {
	return '<a target="_blank" class="w-240" href="/bridge2/information/index_detail.shtml?bound_id=' + data
		.BOND_NUM + '">' + data.AUDIT_NAME + '</a>';
}

var status_transfer = function(data) {
	if (data.AUDIT_STATUS == "0") {
		return "已申报";
	} else if (data.AUDIT_STATUS == "1") {
		return "已受理";
	} else if (data.AUDIT_STATUS == "2") {
		return "已反馈";
	} else if (data.AUDIT_STATUS == "3") {
		return "已接收反馈意见";
	} else if (data.AUDIT_STATUS == "4") {
		return "通过";
	} else if (data.AUDIT_STATUS == "5") {
		return "未通过";
	} else if (data.AUDIT_STATUS == "8") {
		return "终止";
	} else if (data.AUDIT_SUB_STATUS == "901") {
		return "承销商/管理人超期中止";
	} else if (data.AUDIT_STATUS == "9") {
		return "中止";
	} else if (data.AUDIT_STATUS == "10") {
		return "已回复交易所意见";
	} else if (data.AUDIT_STATUS == "11") {
		return "提交注册";
	} else if (data.AUDIT_STATUS == "12") {
		return "注册生效";
	} else {
		return "-";
	}
}

var number_transfer = function(data) {
	var bondType = data.BOND_TYPE;
	if (bondType == '4') {
		return '-'
	} else {
		return data.PLAN_ISSUE_AMOUNT
	}
}

var contentLink2 = function(data) {
	var listArray = data.LIST1.split(",");
	var listArray1 = data.LIST11.split(",");
	var retu = "";
	for (var i = 0; i < listArray.length; i++) {
		retu += '<a target="_blank" href="/bridge2/information/index_isser.shtml?isser_id=' + listArray1[i] + '">' +
			listArray[i] + '</a><br>';
	}
	return retu;
}

var contentLink3 = function(data) {
	var listArray = data.SHORT_NAME.split(",");
	var listArray1 = data.LIST22.split(",");
	var listArray2 = data.LIST2.split(",");
	var retu = "";
	for (var i = 0; i < listArray.length; i++) {
		retu += '<a target="_blank" href="/bridge2/information/index_unde.shtml?unde_id=' + listArray1[i] +
			'&&unde_name=' + listArray2[i] + '&&bond_type=' + data.BOND_TYPE + '">' + listArray[i] + '</a><br>';
	}
	return retu;
}

$('.hidden-mobile .search-area a.search').click(function() {
	var pattern = new RegExp("[`~!@%#$^&*()=+|{}':;',\\[\\].<>/?~！@#￥……&*（）——|{}【】‘；：”“'。，、？]");
	var kw = $('.hidden-mobile .search-area input').val();
	if (pattern.test(kw) || $.trim(kw) == '') {
		alert("请输入正确的查询条件.");
		return;
	}
	window.open("/bridge2/information/index_search.shtml?key=" + kw);
})

$('.hidden-pc .search-block a.search').click(function() {
	var pattern = new RegExp("[`~!@%#$^&*()=+|{}':;',\\[\\].<>/?~！@#￥……&*（）——|{}【】‘；：”“'。，、？]");
	var kw = $('.hidden-pc .search-block input').val();
	if (pattern.test(kw) || $.trim(kw) == '') {
		alert("请输入正确的查询条件.");
		return;
	}
	location.href = "/bridge2/information/index_search.shtml?key=" + kw;
})


var pathnameArr = window.location.pathname.split('/');
var r = pathnameArr.filter(function(s) {
	return s && s.trim();
});
if (r.length >= 2) {
	//var bannerUrl = '/xhtml/'+r[0]+'/'+r[1] + '/images/banner.jpg';
        var bannerUrl = '/xhtml/bridge2/'+'/'+r[1] + '/images/banner.jpg';
	$('.js_banner').css('background-image', 'url(' + bannerUrl + ')');
}
window.addEventListener('resize', function() {
	paging();
})

function paging() {
	var winW = window.innerWidth;
	if (winW < 768) {
		$('head').append(
			'<style>.paging_text > a,.paging_text > span,.paging_input{display:none;} .paging_text a.paging_pre,.paging_text a.paging_next{display:block;}</style>'
			);
	} else {
		$('#new_class').remove();
	}
}
paging();

function fnSwiper(ele, isAutoplay, delay, speed, effect, swiper) {
	var autoplay1;
	if (isAutoplay == 'true') {
		autoplay1 = {
			delay: delay,
			disableOnInteraction: false
		}
	} else {
		autoplay1 = false;
	}
	new swiper(ele, {
		// direction: 'vertical', // 垂直切换选项
		loop: true, // 循环模式选项
		autoplay: autoplay1,
		effect: effect,
		speed: speed,
		pagination: {
			el: $(ele).find('.swiper-pagination'),
			clickable: true
		},
		navigation: {
			nextEl: $(ele).find('.swiper-button-next'),
			prevEl: $(ele).find('.swiper-button-prev'),
		}
	})

}
