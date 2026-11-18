// node_modules/@lit/reactive-element/css-tag.js
var e = globalThis, t = e.ShadowRoot && (e.ShadyCSS === void 0 || e.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, n = Symbol(), r = /* @__PURE__ */ new WeakMap(), i = class {
	constructor(e, t, r) {
		if (this._$cssResult$ = !0, r !== n) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
		this.cssText = e, this.t = t;
	}
	get styleSheet() {
		let e = this.o, n = this.t;
		if (t && e === void 0) {
			let t = n !== void 0 && n.length === 1;
			t && (e = r.get(n)), e === void 0 && ((this.o = e = new CSSStyleSheet()).replaceSync(this.cssText), t && r.set(n, e));
		}
		return e;
	}
	toString() {
		return this.cssText;
	}
}, a = (e) => new i(typeof e == "string" ? e : e + "", void 0, n), o = (e, ...t) => new i(e.length === 1 ? e[0] : t.reduce((t, n, r) => t + ((e) => {
	if (!0 === e._$cssResult$) return e.cssText;
	if (typeof e == "number") return e;
	throw Error("Value passed to 'css' function must be a 'css' function result: " + e + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
})(n) + e[r + 1], e[0]), e, n), s = (n, r) => {
	if (t) n.adoptedStyleSheets = r.map((e) => e instanceof CSSStyleSheet ? e : e.styleSheet);
	else for (let t of r) {
		let r = document.createElement("style"), i = e.litNonce;
		i !== void 0 && r.setAttribute("nonce", i), r.textContent = t.cssText, n.appendChild(r);
	}
}, c = t ? (e) => e : (e) => e instanceof CSSStyleSheet ? ((e) => {
	let t = "";
	for (let n of e.cssRules) t += n.cssText;
	return a(t);
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: d, getOwnPropertyNames: f, getOwnPropertySymbols: ee, getPrototypeOf: te } = Object, p = globalThis, m = p.trustedTypes, ne = m ? m.emptyScript : "", re = p.reactiveElementPolyfillSupport, h = (e, t) => e, g = {
	toAttribute(e, t) {
		switch (t) {
			case Boolean:
				e = e ? ne : null;
				break;
			case Object:
			case Array: e = e == null ? e : JSON.stringify(e);
		}
		return e;
	},
	fromAttribute(e, t) {
		let n = e;
		switch (t) {
			case Boolean:
				n = e !== null;
				break;
			case Number:
				n = e === null ? null : Number(e);
				break;
			case Object:
			case Array: try {
				n = JSON.parse(e);
			} catch {
				n = null;
			}
		}
		return n;
	}
}, _ = (e, t) => !l(e, t), v = {
	attribute: !0,
	type: String,
	converter: g,
	reflect: !1,
	useDefault: !1,
	hasChanged: _
};
Symbol.metadata ??= Symbol("metadata"), p.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var y = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = v) {
		if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
			let n = Symbol(), r = this.getPropertyDescriptor(e, n, t);
			r !== void 0 && u(this.prototype, e, r);
		}
	}
	static getPropertyDescriptor(e, t, n) {
		let { get: r, set: i } = d(this.prototype, e) ?? {
			get() {
				return this[t];
			},
			set(e) {
				this[t] = e;
			}
		};
		return {
			get: r,
			set(t) {
				let a = r?.call(this);
				i?.call(this, t), this.requestUpdate(e, a, n);
			},
			configurable: !0,
			enumerable: !0
		};
	}
	static getPropertyOptions(e) {
		return this.elementProperties.get(e) ?? v;
	}
	static _$Ei() {
		if (this.hasOwnProperty(h("elementProperties"))) return;
		let e = te(this);
		e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
	}
	static finalize() {
		if (this.hasOwnProperty(h("finalized"))) return;
		if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(h("properties"))) {
			let e = this.properties, t = [...f(e), ...ee(e)];
			for (let n of t) this.createProperty(n, e[n]);
		}
		let e = this[Symbol.metadata];
		if (e !== null) {
			let t = litPropertyMetadata.get(e);
			if (t !== void 0) for (let [e, n] of t) this.elementProperties.set(e, n);
		}
		this._$Eh = /* @__PURE__ */ new Map();
		for (let [e, t] of this.elementProperties) {
			let n = this._$Eu(e, t);
			n !== void 0 && this._$Eh.set(n, e);
		}
		this.elementStyles = this.finalizeStyles(this.styles);
	}
	static finalizeStyles(e) {
		let t = [];
		if (Array.isArray(e)) {
			let n = new Set(e.flat(1 / 0).reverse());
			for (let e of n) t.unshift(c(e));
		} else e !== void 0 && t.push(c(e));
		return t;
	}
	static _$Eu(e, t) {
		let n = t.attribute;
		return !1 === n ? void 0 : typeof n == "string" ? n : typeof e == "string" ? e.toLowerCase() : void 0;
	}
	constructor() {
		super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
	}
	_$Ev() {
		this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((e) => e(this));
	}
	addController(e) {
		(this._$EO ??= /* @__PURE__ */ new Set()).add(e), this.renderRoot !== void 0 && this.isConnected && e.hostConnected?.();
	}
	removeController(e) {
		this._$EO?.delete(e);
	}
	_$E_() {
		let e = /* @__PURE__ */ new Map(), t = this.constructor.elementProperties;
		for (let n of t.keys()) this.hasOwnProperty(n) && (e.set(n, this[n]), delete this[n]);
		e.size > 0 && (this._$Ep = e);
	}
	createRenderRoot() {
		let e = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
		return s(e, this.constructor.elementStyles), e;
	}
	connectedCallback() {
		this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(!0), this._$EO?.forEach((e) => e.hostConnected?.());
	}
	enableUpdating(e) {}
	disconnectedCallback() {
		this._$EO?.forEach((e) => e.hostDisconnected?.());
	}
	attributeChangedCallback(e, t, n) {
		this._$AK(e, n);
	}
	_$ET(e, t) {
		let n = this.constructor.elementProperties.get(e), r = this.constructor._$Eu(e, n);
		if (r !== void 0 && !0 === n.reflect) {
			let i = (n.converter?.toAttribute === void 0 ? g : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? g : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? _)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
			this.C(e, t, n);
		}
		!1 === this.isUpdatePending && (this._$ES = this._$EP());
	}
	C(e, t, { useDefault: n, reflect: r, wrapped: i }, a) {
		n && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(e) && (this._$Ej.set(e, a ?? t ?? this[e]), !0 !== i || a !== void 0) || (this._$AL.has(e) || (this.hasUpdated || n || (t = void 0), this._$AL.set(e, t)), !0 === r && this._$Em !== e && (this._$Eq ??= /* @__PURE__ */ new Set()).add(e));
	}
	async _$EP() {
		this.isUpdatePending = !0;
		try {
			await this._$ES;
		} catch (e) {
			Promise.reject(e);
		}
		let e = this.scheduleUpdate();
		return e != null && await e, !this.isUpdatePending;
	}
	scheduleUpdate() {
		return this.performUpdate();
	}
	performUpdate() {
		if (!this.isUpdatePending) return;
		if (!this.hasUpdated) {
			if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
				for (let [e, t] of this._$Ep) this[e] = t;
				this._$Ep = void 0;
			}
			let e = this.constructor.elementProperties;
			if (e.size > 0) for (let [t, n] of e) {
				let { wrapped: e } = n, r = this[t];
				!0 !== e || this._$AL.has(t) || r === void 0 || this.C(t, void 0, n, r);
			}
		}
		let e = !1, t = this._$AL;
		try {
			e = this.shouldUpdate(t), e ? (this.willUpdate(t), this._$EO?.forEach((e) => e.hostUpdate?.()), this.update(t)) : this._$EM();
		} catch (t) {
			throw e = !1, this._$EM(), t;
		}
		e && this._$AE(t);
	}
	willUpdate(e) {}
	_$AE(e) {
		this._$EO?.forEach((e) => e.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e);
	}
	_$EM() {
		this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
	}
	get updateComplete() {
		return this.getUpdateComplete();
	}
	getUpdateComplete() {
		return this._$ES;
	}
	shouldUpdate(e) {
		return !0;
	}
	update(e) {
		this._$Eq &&= this._$Eq.forEach((e) => this._$ET(e, this[e])), this._$EM();
	}
	updated(e) {}
	firstUpdated(e) {}
};
y.elementStyles = [], y.shadowRootOptions = { mode: "open" }, y[h("elementProperties")] = /* @__PURE__ */ new Map(), y[h("finalized")] = /* @__PURE__ */ new Map(), re?.({ ReactiveElement: y }), (p.reactiveElementVersions ??= []).push("2.1.2");
// node_modules/lit-html/lit-html.js
var b = globalThis, x = (e) => e, S = b.trustedTypes, ie = S ? S.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, C = "$lit$", w = `lit$${Math.random().toFixed(9).slice(2)}$`, T = "?" + w, ae = `<${T}>`, E = document, D = () => E.createComment(""), O = (e) => e === null || typeof e != "object" && typeof e != "function", k = Array.isArray, oe = (e) => k(e) || typeof e?.[Symbol.iterator] == "function", A = "[ 	\n\f\r]", j = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, se = /-->/g, ce = />/g, M = RegExp(`>|${A}(?:([^\\s"'>=/]+)(${A}*=${A}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), le = /'/g, ue = /"/g, N = /^(?:script|style|textarea|title)$/i, P = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), F = Symbol.for("lit-noChange"), I = Symbol.for("lit-nothing"), L = /* @__PURE__ */ new WeakMap(), R = E.createTreeWalker(E, 129);
function z(e, t) {
	if (!k(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return ie === void 0 ? t : ie.createHTML(t);
}
var de = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = j;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === j ? c[1] === "!--" ? o = se : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = M) : (N.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = M) : o = ce : o === M ? c[0] === ">" ? (o = i ?? j, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? M : c[3] === "\"" ? ue : le) : o === ue || o === le ? o = M : o === se || o === ce ? o = j : (o = M, i = void 0);
		let d = o === M && e[t + 1].startsWith("/>") ? " " : "";
		a += o === j ? n + ae : l >= 0 ? (r.push(s), n.slice(0, l) + C + n.slice(l) + w + d) : n + w + (l === -2 ? t : d);
	}
	return [z(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, B = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = de(t, n);
		if (this.el = e.createElement(l, r), R.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = R.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(C)) {
					let t = u[o++], n = i.getAttribute(e).split(w), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? pe : r[1] === "?" ? me : r[1] === "@" ? he : U
					}), i.removeAttribute(e);
				} else e.startsWith(w) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (N.test(i.tagName)) {
					let e = i.textContent.split(w), t = e.length - 1;
					if (t > 0) {
						i.textContent = S ? S.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], D()), R.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], D());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === T) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(w, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += w.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = E.createElement("template");
		return n.innerHTML = e, n;
	}
};
function V(e, t, n = e, r) {
	if (t === F) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = O(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = V(e, i._$AS(e, t.values), i, r)), t;
}
var fe = class {
	constructor(e, t) {
		this._$AV = [], this._$AN = void 0, this._$AD = e, this._$AM = t;
	}
	get parentNode() {
		return this._$AM.parentNode;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	u(e) {
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? E).importNode(t, !0);
		R.currentNode = r;
		let i = R.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new H(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new ge(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = R.nextNode(), a++);
		}
		return R.currentNode = E, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, H = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = I, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
	}
	get parentNode() {
		let e = this._$AA.parentNode, t = this._$AM;
		return t !== void 0 && e?.nodeType === 11 && (e = t.parentNode), e;
	}
	get startNode() {
		return this._$AA;
	}
	get endNode() {
		return this._$AB;
	}
	_$AI(e, t = this) {
		e = V(this, e, t), O(e) ? e === I || e == null || e === "" ? (this._$AH !== I && this._$AR(), this._$AH = I) : e !== this._$AH && e !== F && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? oe(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== I && O(this._$AH) ? this._$AA.nextSibling.data = e : this.T(E.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = B.createElement(z(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new fe(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = L.get(e.strings);
		return t === void 0 && L.set(e.strings, t = new B(e)), t;
	}
	k(t) {
		k(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(D()), this.O(D()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = x(e).nextSibling;
			x(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, U = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = I, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = I;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = V(this, e, t, 0), a = !O(e) || e !== this._$AH && e !== F, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = V(this, r[n + o], t, o), s === F && (s = this._$AH[o]), a ||= !O(s) || s !== this._$AH[o], s === I ? e = I : e !== I && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === I ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, pe = class extends U {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === I ? void 0 : e;
	}
}, me = class extends U {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== I);
	}
}, he = class extends U {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = V(this, e, t, 0) ?? I) === F) return;
		let n = this._$AH, r = e === I && n !== I || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== I && (n === I || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, ge = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		V(this, e);
	}
}, _e = b.litHtmlPolyfillSupport;
_e?.(B, H), (b.litHtmlVersions ??= []).push("3.3.3");
var ve = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new H(t.insertBefore(D(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, W = globalThis, G = class extends y {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = ve(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return F;
	}
};
G._$litElement$ = !0, G.finalized = !0, W.litElementHydrateSupport?.({ LitElement: G });
var ye = W.litElementPolyfillSupport;
ye?.({ LitElement: G }), (W.litElementVersions ??= []).push("4.2.2");
// src/localize.ts
var K = {
	en: {
		panel: {
			title: "Boiler",
			loading: "Loading…",
			not_running: "Smart Boiler is not running. Check its entry under Settings → Devices & services.",
			error: "The page could not read Smart Boiler's data: {message}"
		},
		status: {
			monitoring: "Monitoring",
			monitoring_detail: "Control is not set up: the plugin watches the boiler and counts.",
			burner_on: "The burner is on.",
			burner_off: "The burner is off."
		},
		control: {
			label: "Control",
			experimental: "(experimental)",
			hint_on: "Switching off hands the boiler back to its own settings.",
			hint_off: "Switching on asks for confirmation.",
			admin_only: "Only an administrator can change this.",
			unavailable: "Not available now.",
			confirm_off_title: "Switch control off?",
			confirm_off_body: "The plugin stops setting the water temperature and hands the boiler back to its own settings. It keeps watching and counting.",
			confirm_off: "Switch off",
			confirm_on_title: "Switch control on?",
			confirm_on_body: "Control is experimental. The plugin starts setting the boiler's water temperature from the heating curve. You can switch it off at any time, and the boiler returns to its own settings.",
			confirm_on: "Switch on",
			cancel: "Cancel",
			failed: "The switch did not change: {message}"
		},
		tiles: {
			water: "Water — the plugin asks",
			water_confirmed: "confirmed by the boiler",
			water_waiting: "waiting for the boiler to confirm",
			water_none: "nothing asked now",
			flow: "Flow",
			flow_detail: "water leaving the boiler",
			return: "Return",
			return_detail: "water coming back",
			return_condensing: "below 55 °C — the boiler condenses",
			outdoor: "Outdoor",
			outdoor_sensor: "the boiler's sensor",
			outdoor_weather: "from the weather",
			flame: "Flame",
			flame_on: "On",
			flame_off: "Off",
			flame_hot_water: "hot water",
			flame_modulation: "modulation {value} %",
			rooms: "Rooms",
			rooms_value: "{calling} of {total}",
			rooms_detail: "calling for heat"
		}
	},
	pl: {
		panel: {
			title: "Kocioł",
			loading: "Wczytywanie…",
			not_running: "Smart Boiler nie działa. Sprawdź jego wpis w Ustawienia → Urządzenia i usługi.",
			error: "Strona nie mogła odczytać danych Smart Boiler: {message}"
		},
		status: {
			monitoring: "Obserwacja",
			monitoring_detail: "Sterowanie nie jest skonfigurowane: wtyczka obserwuje kocioł i liczy.",
			burner_on: "Palnik pali.",
			burner_off: "Palnik nie pali."
		},
		control: {
			label: "Sterowanie",
			experimental: "(eksperymentalne)",
			hint_on: "Wyłączenie oddaje kocioł jego własnym ustawieniom.",
			hint_off: "Włączenie wymaga potwierdzenia.",
			admin_only: "Zmienić to może tylko administrator.",
			unavailable: "Teraz niedostępne.",
			confirm_off_title: "Wyłączyć sterowanie?",
			confirm_off_body: "Wtyczka przestanie ustawiać temperaturę wody i odda kocioł jego własnym ustawieniom. Dalej będzie obserwować i liczyć.",
			confirm_off: "Wyłącz",
			confirm_on_title: "Włączyć sterowanie?",
			confirm_on_body: "Sterowanie jest eksperymentalne. Wtyczka zacznie ustawiać temperaturę wody w kotle według krzywej grzewczej. W każdej chwili możesz je wyłączyć, a kocioł wróci do swoich ustawień.",
			confirm_on: "Włącz",
			cancel: "Anuluj",
			failed: "Przełącznik się nie zmienił: {message}"
		},
		tiles: {
			water: "Woda — prośba wtyczki",
			water_confirmed: "kocioł potwierdził",
			water_waiting: "czeka na potwierdzenie kotła",
			water_none: "teraz bez prośby",
			flow: "Zasilanie",
			flow_detail: "woda wychodząca z kotła",
			return: "Powrót",
			return_detail: "woda wracająca",
			return_condensing: "poniżej 55 °C — kocioł kondensuje",
			outdoor: "Na zewnątrz",
			outdoor_sensor: "czujnik kotła",
			outdoor_weather: "z pogody",
			flame: "Płomień",
			flame_on: "Pali",
			flame_off: "Nie pali",
			flame_hot_water: "ciepła woda",
			flame_modulation: "modulacja {value} %",
			rooms: "Pokoje",
			rooms_value: "{calling} z {total}",
			rooms_detail: "woła o ciepło"
		}
	}
};
function be(e) {
	if (!e) return K.en;
	let t = e.toLowerCase();
	return K[t] ?? K[t.split("-")[0]] ?? K.en;
}
function q(e, t) {
	let n = e;
	for (let e of t.split(".")) {
		if (typeof n != "object") return;
		n = n[e];
	}
	return typeof n == "string" ? n : void 0;
}
function J(e, t, n) {
	let r = q(be(e), t) ?? q(K.en, t) ?? t;
	return n ? r.replace(/\{(\w+)\}/g, (e, t) => n[t] ?? e) : r;
}
// src/format.ts
var xe = /* @__PURE__ */ new Set([
	"unknown",
	"unavailable",
	"none",
	""
]);
function Y(e) {
	if (e == null || xe.has(e)) return null;
	let t = Number(e);
	return Number.isFinite(t) ? t : null;
}
function Se(e, t, n = 1) {
	if (e == null || !Number.isFinite(e)) return "—";
	try {
		return new Intl.NumberFormat(t, {
			minimumFractionDigits: n,
			maximumFractionDigits: n
		}).format(e);
	} catch {
		return e.toFixed(n);
	}
}
function X(e, t) {
	return e == null ? "—" : `${Se(e, t, 1)} °C`;
}
// src/live.ts
var Ce = 55;
function Z(e, t) {
	return t ? e.states[t] : void 0;
}
function Q(e, t) {
	return Z(e, e.installation.signals[t]);
}
function $(e, t) {
	return Z(e, e.installation.entities[t]);
}
function we(e) {
	return [...new Set(e.circuits.flatMap((e) => e.zones.map((e) => e.entity_id)))];
}
function Te(e) {
	let t = $(e, "demand_count")?.attributes.calling_zones;
	return Array.isArray(t) ? t.filter((e) => typeof e == "string") : [];
}
function Ee(e) {
	return Q(e, "flame")?.state === "on";
}
function De(e) {
	let { t } = e, n = Ee(e), r = $(e, "control_state");
	if (r && r.state !== "unavailable") {
		let t = r.attributes.reasons_text;
		return {
			title: e.stateText(r),
			detail: typeof t == "string" ? t : "",
			flame: n,
			code: r.state
		};
	}
	let i = Q(e, "flame") ? t(n ? "status.burner_on" : "status.burner_off") : t("status.monitoring_detail");
	return {
		title: t("status.monitoring"),
		detail: i,
		flame: n,
		code: "monitoring"
	};
}
function Oe(e) {
	let t = e.installation.entities.control, n = Z(e, t);
	return !t || !n ? null : {
		entityId: t,
		on: n.state === "on",
		available: n.state !== "unavailable"
	};
}
function ke(e) {
	let { t, language: n, installation: r } = e, i = [], a = $(e, "control_setpoint");
	if (a) {
		let e = Y(String(a.attributes.requested ?? "")), r = Y(String(a.attributes.read_back ?? "")), o = e != null && r != null && Math.abs(e - r) < .5;
		i.push({
			key: "water",
			label: t("tiles.water"),
			value: X(e, n),
			detail: t(e == null ? "tiles.water_none" : o ? "tiles.water_confirmed" : "tiles.water_waiting")
		});
	}
	let o = Q(e, "flow");
	o && i.push({
		key: "flow",
		label: t("tiles.flow"),
		value: X(Y(o.state), n),
		detail: t("tiles.flow_detail")
	});
	let s = Q(e, "return");
	if (s) {
		let e = Y(s.state), a = r.boiler.condensing && e != null && e < Ce;
		i.push({
			key: "return",
			label: t("tiles.return"),
			value: X(e, n),
			detail: t(a ? "tiles.return_condensing" : "tiles.return_detail")
		});
	}
	let c = Q(e, "outdoor"), l = Z(e, r.weather), u = l ? Y(String(l.attributes.temperature ?? "")) : null;
	if (c || u != null) {
		let e = c ? Y(c.state) : null;
		i.push({
			key: "outdoor",
			label: t("tiles.outdoor"),
			value: X(e ?? u, n),
			detail: t(e == null ? "tiles.outdoor_weather" : "tiles.outdoor_sensor")
		});
	}
	let d = Q(e, "flame");
	if (d) {
		let r = d.state === "on", a = Y(Q(e, "modulation")?.state), o = Q(e, "dhw_active")?.state === "on";
		i.push({
			key: "flame",
			label: t("tiles.flame"),
			value: t(r ? "tiles.flame_on" : "tiles.flame_off"),
			detail: r && o ? t("tiles.flame_hot_water") : r && a != null ? t("tiles.flame_modulation", { value: Se(a, n, 0) }) : ""
		});
	}
	let f = we(r);
	return f.length && $(e, "demand_count") && i.push({
		key: "rooms",
		label: t("tiles.rooms"),
		value: t("tiles.rooms_value", {
			calling: String(Te(e).filter((e) => f.includes(e)).length),
			total: String(f.length)
		}),
		detail: t("tiles.rooms_detail")
	}), i;
}
function Ae(e) {
	return {
		status: De(e),
		control: Oe(e),
		tiles: ke(e)
	};
}
// src/overview.ts
var je = "vtherm-smart-boiler-overview", Me = "M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.3 1.6 1 2.6 2 3.1C11 9 11.3 6 12 3z", Ne = class extends G {
	static {
		this.properties = {
			hass: { attribute: !1 },
			installation: { attribute: !1 },
			confirming: { state: !0 },
			error: { state: !0 }
		};
	}
	constructor() {
		super(), this.confirming = !1, this.error = "";
	}
	t(e, t) {
		return J(this.hass?.language, e, t);
	}
	view() {
		let e = this.hass;
		return !e || !this.installation ? null : Ae({
			installation: this.installation,
			states: e.states,
			language: e.locale?.language ?? e.language,
			t: (e, t) => this.t(e, t),
			stateText: (t) => e.formatEntityState?.(t) ?? t.state
		});
	}
	get isAdmin() {
		return this.hass?.user?.is_admin === !0;
	}
	ask() {
		this.error = "", this.confirming = !0;
	}
	async decide(e, t) {
		this.confirming = !1;
		let n = t.control;
		if (e && n && this.hass) try {
			await this.hass.callService("switch", n.on ? "turn_off" : "turn_on", { entity_id: n.entityId });
		} catch (e) {
			let t = e instanceof Error ? e.message : String(e?.message ?? e);
			this.error = this.t("control.failed", { message: t });
		}
	}
	updated() {
		let e = this.renderRoot.querySelector("dialog");
		e && (this.confirming && !e.open && e.showModal(), !this.confirming && e.open && e.close());
	}
	render() {
		let e = this.view();
		if (!e) return I;
		let { status: t, control: n, tiles: r } = e, i = n !== null && n.available && this.isAdmin, a = n ? n.available ? this.isAdmin ? n.on ? this.t("control.hint_on") : this.t("control.hint_off") : this.t("control.admin_only") : this.t("control.unavailable") : "";
		return P`
      <section class="card hero">
        <div class="status">
          <div class="flame ${t.flame ? "lit" : ""}" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d=${Me}></path></svg>
          </div>
          <div class="words">
            <h2>${t.title}</h2>
            ${t.detail ? P`<p>${t.detail}</p>` : I}
          </div>
        </div>
        ${n ? P`<div class="control">
              <div class="label">
                <div>${this.t("control.label")} <span class="muted">${this.t("control.experimental")}</span></div>
                <div class="muted small">${a}</div>
              </div>
              <button
                class="switch ${n.on ? "on" : ""}"
                role="switch"
                aria-checked=${n.on ? "true" : "false"}
                aria-label=${this.t("control.label")}
                ?disabled=${!i}
                @click=${() => this.ask()}
              >
                <span class="knob"></span>
              </button>
            </div>` : I}
        ${this.error ? P`<p class="error" role="alert">${this.error}</p>` : I}
      </section>

      ${r.length ? P`<section class="tiles" aria-label=${this.t("panel.title")}>
            ${r.map((e) => P`<div class="card tile">
                <div class="tile-label">${e.label}</div>
                <div class="tile-value">${e.value}</div>
                <div class="muted small">${e.detail}</div>
              </div>`)}
          </section>` : I}

      ${n ? P`<dialog aria-labelledby="confirm-title" @cancel=${() => this.confirming = !1}>
            <h2 id="confirm-title">
              ${n.on ? this.t("control.confirm_off_title") : this.t("control.confirm_on_title")}
            </h2>
            <p>${n.on ? this.t("control.confirm_off_body") : this.t("control.confirm_on_body")}</p>
            <div class="actions">
              <button class="text" @click=${() => this.decide(!1, e)}>${this.t("control.cancel")}</button>
              <button class="primary" @click=${() => this.decide(!0, e)}>
                ${n.on ? this.t("control.confirm_off") : this.t("control.confirm_on")}
              </button>
            </div>
          </dialog>` : I}
    `;
	}
	static {
		this.styles = o`
    :host {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 16px;
      box-sizing: border-box;
      min-width: 0;
    }
    .hero {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 16px 24px;
    }
    .status {
      display: flex;
      align-items: center;
      gap: 16px;
      flex: 999 1 420px;
      min-width: 0;
    }
    .flame {
      width: 54px;
      height: 54px;
      border-radius: 50%;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
      display: flex;
      align-items: center;
      justify-content: center;
      flex: none;
      color: var(--disabled-text-color, #9e9e9e);
    }
    .flame.lit {
      color: var(--state-climate-heat-color, #ff8100);
    }
    .flame svg {
      width: 30px;
      height: 30px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    h2 {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
    }
    .words p {
      margin: 4px 0 0;
      color: var(--secondary-text-color);
    }
    .control {
      display: flex;
      align-items: center;
      gap: 14px;
      flex: 1 1 340px;
      justify-content: flex-end;
      text-align: right;
    }
    .label > div:first-child {
      white-space: nowrap;
    }
    .muted {
      color: var(--secondary-text-color);
    }
    .small {
      font-size: 12px;
    }
    .switch {
      appearance: none;
      border: 0;
      padding: 0;
      width: 52px;
      height: 32px;
      border-radius: 16px;
      background: var(--disabled-color, #bdbdbd);
      position: relative;
      cursor: pointer;
      flex: none;
    }
    .switch.on {
      background: var(--primary-color);
    }
    .switch:disabled {
      cursor: not-allowed;
      opacity: 0.5;
    }
    .switch:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 3px;
    }
    .knob {
      position: absolute;
      top: 4px;
      left: 4px;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
      transition: left 0.15s;
    }
    .switch.on .knob {
      left: 24px;
    }
    .error {
      flex-basis: 100%;
      margin: 0;
      color: var(--error-color, #db4437);
    }
    .tiles {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
    }
    .tile {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .tile-label {
      font-size: 13px;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    .tile-value {
      font-size: 26px;
      font-weight: 600;
      line-height: 1.1;
      font-variant-numeric: tabular-nums;
    }
    dialog {
      border: 0;
      border-radius: var(--ha-dialog-border-radius, 16px);
      padding: 24px;
      max-width: 440px;
      width: calc(100% - 32px);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
    }
    dialog::backdrop {
      background: rgba(0, 0, 0, 0.45);
    }
    dialog h2 {
      font-size: 20px;
      margin-bottom: 8px;
    }
    dialog p {
      margin: 0;
      color: var(--secondary-text-color);
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 20px;
    }
    .actions button {
      appearance: none;
      border: 0;
      border-radius: 10px;
      min-height: 40px;
      padding: 0 16px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }
    .actions .text {
      background: transparent;
      color: var(--primary-color);
    }
    .actions .primary {
      background: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
  `;
	}
};
customElements.get("vtherm-smart-boiler-overview") || customElements.define(je, Ne);
// src/panel.ts
var Pe = "vtherm-smart-boiler-panel", Fe = class extends G {
	static {
		this.properties = {
			hass: { attribute: !1 },
			narrow: { type: Boolean },
			panel: { attribute: !1 },
			load: { state: !0 }
		};
	}
	constructor() {
		super(), this.requested = !1, this.narrow = !1, this.load = { kind: "loading" };
	}
	t(e, t) {
		return J(this.hass?.language, e, t);
	}
	willUpdate() {
		this.hass && !this.requested && (this.requested = !0, this.fetchInstallation());
	}
	async fetchInstallation() {
		if (this.hass) {
			this.load = { kind: "loading" };
			try {
				let e = await this.hass.callWS({ type: "vtherm_smart_boiler/installation" });
				this.load = {
					kind: "ready",
					installation: e
				};
			} catch (e) {
				let t = e?.code, n = e?.message;
				this.load = t === "not_running" ? { kind: "not_running" } : {
					kind: "error",
					message: typeof n == "string" ? n : String(e)
				};
			}
		}
	}
	body() {
		switch (this.load.kind) {
			case "loading": return P`<p class="note">${this.t("panel.loading")}</p>`;
			case "not_running": return P`<p class="note">${this.t("panel.not_running")}</p>`;
			case "error": return P`<p class="note error" role="alert">
          ${this.t("panel.error", { message: this.load.message })}
        </p>`;
			case "ready": return P`<vtherm-smart-boiler-overview
          .hass=${this.hass}
          .installation=${this.load.installation}
        ></vtherm-smart-boiler-overview>`;
		}
	}
	render() {
		return P`
      <header class="toolbar">
        ${this.narrow ? P`<ha-menu-button .hass=${this.hass} .narrow=${this.narrow}></ha-menu-button>` : I}
        <h1>${this.t("panel.title")}</h1>
      </header>
      <main>${this.body()}</main>
    `;
	}
	static {
		this.styles = o`
    :host {
      display: block;
      min-height: 100%;
      background: var(--primary-background-color);
      color: var(--primary-text-color);
      font-family: var(--ha-font-family-body, Roboto, sans-serif);
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: var(--header-height, 56px);
      padding: 0 16px;
      box-sizing: border-box;
      background: var(--app-header-background-color, var(--primary-color));
      color: var(--app-header-text-color, var(--text-primary-color));
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 400;
    }
    main {
      max-width: 1240px;
      margin: 0 auto;
      padding: 16px;
    }
    .note {
      color: var(--secondary-text-color);
    }
    .error {
      color: var(--error-color, #db4437);
    }
  `;
	}
};
customElements.get("vtherm-smart-boiler-panel") || customElements.define(Pe, Fe);
export { Pe as PANEL_TAG, Fe as SmartBoilerPanel };
